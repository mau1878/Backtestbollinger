import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
import random
import plotly.graph_objects as go
from plotly.subplots import make_subplots



# Add this near the top of your app
# Add this near the top of your app
with st.expander("Cómo obtener tu MTZ Web Key"):
    st.markdown("""
    Para obtener tu MTZ Web Key:
    1. Ingresa a matriz.cocos.xoms.com.ar
    2. Inicia sesión en tu cuenta
    3. Abre las Herramientas de Desarrollo del navegador (F12)
    4. Ve a Aplicación > Cookies
    5. Busca el valor de la cookie '_mtz_web_key'
    6. Copia y pega ese valor en el campo MTZ Web Key de la barra lateral

    ⚠️ Mantén tu MTZ Web Key privada y nunca la compartas con otros.
    """)
# Data fetching functions
def construct_symbol_id(ticker, market_type):
    return f"bm_MERV_{ticker}_{market_type}"

def get_stock_data(symbol_id, lookback_days, mtz_web_key):
    """Fetch data from Matriz Cocos API"""
    if not mtz_web_key:
        st.error("Por favor, ingresa tu MTZ Web Key en la barra lateral.")
        return None

    cookies = {
        '_mtz_web_key': mtz_web_key,
    }

    # Rest of the function remains the same...

    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'de-DE,de;q=0.9,es-AR;q=0.8,es;q=0.7,en-DE;q=0.6,en;q=0.5,en-US;q=0.4',
        'dnt': '1',
        'priority': 'u=1, i',
        'referer': f'https://matriz.cocos.xoms.com.ar/security/{symbol_id}?interval=1',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    }

    # Calculate timestamps
    end_time = datetime.now()
    start_time = end_time - timedelta(days=lookback_days)

    # Generate timestamp for _ds parameter
    current_timestamp = int(datetime.now().timestamp() * 1000)
    random_suffix = random.randint(100000, 999999)

    params = {
        'resolution': '1',  # 1-minute resolution
        'from': start_time.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
        'to': end_time.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
        '_ds': f'{current_timestamp}-{random_suffix}',
    }

    try:
        response = requests.get(
            f'https://matriz.cocos.xoms.com.ar/api/v2/series/securities/{symbol_id}',
            params=params,
            cookies=cookies,
            headers=headers,
            timeout=10
        )

        if response.status_code != 200:
            st.error(f"API request failed with status code: {response.status_code}")
            st.write("Response content:", response.text[:500])
            return None

        data = response.json()

        if data.get('noData', True):
            st.error("No data available for the specified period")
            return None

        # Convert API response to DataFrame
        series_data = data.get('series', [])
        df_data = []

        for candle in series_data:
            df_data.append({
                'timestamp': pd.to_datetime(candle['d'], utc=True),
                'Open': candle['o'],
                'High': candle['h'],
                'Low': candle['l'],
                'Close': candle['c'],
                'Volume': candle['v']
            })

        df = pd.DataFrame(df_data)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)

        # Convert UTC to Argentina time (GMT-3)
        df.index = df.index.tz_convert('America/Argentina/Buenos_Aires')

        # Filter for trading hours (11:00 to 17:00 Argentina time)
        df = df.between_time('11:00', '17:00')

        # Remove days with no trading activity (volume = 0)
        df = df[df['Volume'] > 0]

        # Resample to 5-minute intervals
        df_5min = df.resample('5T').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        })

        # Remove any rows with NaN values that might have been created during resampling
        df_5min = df_5min.dropna()

        # Remove periods with no trading activity after resampling
        df_5min = df_5min[df_5min['Volume'] > 0]

        return df_5min

    except Exception as e:
        st.error(f"Error fetching data: {str(e)}")
        return None

# Strategy functions
def calculate_bollinger_bands(df, window=20, num_std=2):
    # Only calculate on days with actual trading activity
    df['MA'] = df['Close'].rolling(window=window, min_periods=1).mean()
    df['STD'] = df['Close'].rolling(window=window, min_periods=1).std()
    df['Upper'] = df['MA'] + (df['STD'] * num_std)
    df['Lower'] = df['MA'] - (df['STD'] * num_std)
    return df

def backtest_buy_hold(df, initial_investment=100000):
    start_price = df['Close'].iloc[0]
    end_price = df['Close'].iloc[-1]
    shares = initial_investment / start_price
    final_value = shares * end_price
    return final_value

def backtest_bollinger_strategy(df, initial_investment=100000):
    position = 0  # 0: out of market, 1: in market
    cash = initial_investment
    shares = 0
    trades = []

    for i in range(len(df)):
        price = df['Close'].iloc[i]

        if position == 0 and price <= df['Lower'].iloc[i]:
            # Buy signal
            shares = cash / price
            cash = 0
            position = 1
            trades.append({
                'timestamp': df.index[i],
                'type': 'buy',
                'price': price,
                'shares': shares
            })

        elif position == 1 and price >= df['Upper'].iloc[i]:
            # Sell signal
            cash = shares * price
            shares = 0
            position = 0
            trades.append({
                'timestamp': df.index[i],
                'type': 'sell',
                'price': price,
                'shares': shares
            })

    # Close position at the end if still in market
    if position == 1:
        cash = shares * df['Close'].iloc[-1]

    return cash, trades

def plot_strategy(df, trades):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03, subplot_titles=('Price and Bollinger Bands', 'Volume'),
                        row_heights=[0.7, 0.3])

    # Add candlestick
    fig.add_trace(go.Candlestick(x=df.index,
                                open=df['Open'],
                                high=df['High'],
                                low=df['Low'],
                                close=df['Close'],
                                name='OHLC'),
                  row=1, col=1)

    # Add Bollinger Bands
    fig.add_trace(go.Scatter(x=df.index, y=df['Upper'],
                            line=dict(color='gray', dash='dash'),
                            name='Upper Band',
                            mode='lines'),
                  row=1, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['Lower'],
                            line=dict(color='gray', dash='dash'),
                            name='Lower Band',
                            mode='lines'),
                  row=1, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['MA'],
                            line=dict(color='blue', dash='dash'),
                            name='Moving Average',
                            mode='lines'),
                  row=1, col=1)

    # Add buy/sell markers
    buy_points = [t['timestamp'] for t in trades if t['type'] == 'buy']
    sell_points = [t['timestamp'] for t in trades if t['type'] == 'sell']

    buy_prices = [df.loc[t]['Close'] for t in buy_points]
    sell_prices = [df.loc[t]['Close'] for t in sell_points]

    fig.add_trace(go.Scatter(x=buy_points, y=buy_prices,
                            mode='markers',
                            marker=dict(symbol='triangle-up', size=15, color='green'),
                            name='Buy Signal'),
                  row=1, col=1)

    fig.add_trace(go.Scatter(x=sell_points, y=sell_prices,
                            mode='markers',
                            marker=dict(symbol='triangle-down', size=15, color='red'),
                            name='Sell Signal'),
                  row=1, col=1)

    # Add volume bars
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'],
                        name='Volume'),
                  row=2, col=1)

    # Update layout
    fig.update_layout(
        title='Trading Strategy Analysis',
        yaxis_title='Price',
        yaxis2_title='Volume',
        xaxis_rangeslider_visible=False,
        xaxis_rangebreaks=[
            dict(bounds=["sat", "mon"]),  # hide weekends
            dict(bounds=[17, 11], pattern="hour"),  # hide non-trading hours
        ]
    )

    # Update y-axes ranges to prevent excessive gaps
    fig.update_yaxes(fixedrange=False)

    return fig

def run_analysis(ticker, market_type, start_date, window, num_std, initial_investment, mtz_web_key):
    # Construct symbol ID and fetch data
    symbol_id = construct_symbol_id(ticker, market_type)
    lookback_days = (datetime.now().date() - start_date).days
    df = get_stock_data(symbol_id, lookback_days, mtz_web_key)

    # Rest of the function remains the same...

    if df is not None:
        # Calculate Bollinger Bands
        df = calculate_bollinger_bands(df, window=window, num_std=num_std)

        # Perform backtests
        buy_hold_result = backtest_buy_hold(df, initial_investment)
        bollinger_result, trades = backtest_bollinger_strategy(df, initial_investment)

        # Display results
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Buy & Hold Strategy", f"${buy_hold_result:,.2f}")
            st.metric("Return", f"{((buy_hold_result/initial_investment - 1) * 100):.2f}%")

        with col2:
            st.metric("Bollinger Strategy", f"${bollinger_result:,.2f}")
            st.metric("Return", f"{((bollinger_result/initial_investment - 1) * 100):.2f}%")

        # Plot the strategy
        fig = plot_strategy(df, trades)
        st.plotly_chart(fig, use_container_width=True)

        # Display trades
        if st.checkbox('Show Trade History'):
            trades_df = pd.DataFrame(trades)
            if not trades_df.empty:
                st.dataframe(trades_df)
    else:
        st.error("Unable to fetch data. Please check your inputs and try again.")


# Streamlit app
st.title('Bollinger Bands Trading Strategy Backtest')

# Create a form for inputs
with st.sidebar.form("strategy_form"):
    st.header('Parámetros de la Estrategia')

    mtz_web_key = st.text_input('MTZ Web Key', type='password',
                               help='Ingresa tu _mtz_web_key de matriz.cocos.xoms.com.ar')

    ticker = st.text_input('Símbolo del Ticker', 'GGAL')
    market_type = st.selectbox('Tipo de Mercado', ['24hs', 'CI'])
    start_date = st.date_input('Fecha de Inicio', datetime.now() - timedelta(days=30))
    window = st.slider('Ventana de Bandas de Bollinger', 5, 50, 20)
    num_std = st.slider('Número de Desviaciones Estándar', 1.0, 3.0, 2.0)
    initial_investment = st.number_input('Inversión Inicial', 100000.0)

    submitted = st.form_submit_button("Ejecutar Análisis")

# Run analysis only when form is submitted
# Run analysis only when form is submitted
if submitted:
    if not mtz_web_key:
        st.error("Por favor, ingresa tu MTZ Web Key en la barra lateral.")
    else:
        with st.spinner('Ejecutando análisis...'):
            run_analysis(ticker, market_type, start_date, window, num_std, initial_investment, mtz_web_key)
else:
    st.info('Por favor, completa los parámetros y haz clic en "Ejecutar Análisis" para iniciar el backtest.')
