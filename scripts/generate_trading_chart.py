"""Generate mock arbitrage chart HTML (composite, strike, TWAP boundary, signals)."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from desk.engine.arbitrage_chart import mock_arbitrage_series

os.makedirs("generated", exist_ok=True)

LIGHTWEIGHT_CHARTS_CDN = (
    "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"
)


def generate_mock_arbitrage_data():
    return mock_arbitrage_series(timesteps=120)["rows"]


def build_chart_html(data_json: str) -> None:
    """Interactive HTML using TradingView Lightweight Charts (v4 standalone API)."""
    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Arbitrage Engine Trading Terminal</title>
    <script src="{LIGHTWEIGHT_CHARTS_CDN}"></script>
    <style>
        body {{
            margin: 0;
            padding: 20px;
            background-color: #0f1115;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: #e1e4ea;
        }}
        #container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            margin-bottom: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .title-badge {{
            background: linear-gradient(135deg, #2962ff, #143ca3);
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
        }}
        #chart {{
            width: 100%;
            height: 600px;
            border: 1px solid #2a2e39;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
        }}
    </style>
</head>
<body>
    <div id="container">
        <div class="header">
            <div>
                <h2 style="margin:0; font-size:22px;">Arbitrage Execution Workspace</h2>
                <p style="margin:5px 0 0 0; font-size:13px; color:#848e9c;">Composite Index vs Settlement Lock Boundary</p>
            </div>
            <div class="title-badge">Rule-Engine Native</div>
        </div>
        <div id="chart"></div>
    </div>

    <script>
        const rawData = {data_json};

        const chartElement = document.getElementById('chart');
        const chart = LightweightCharts.createChart(chartElement, {{
            width: chartElement.clientWidth,
            height: 600,
            layout: {{
                background: {{ type: 'solid', color: '#131722' }},
                textColor: '#d1d4dc',
            }},
            grid: {{
                vertLines: {{ color: 'rgba(42, 46, 57, 0.5)' }},
                horzLines: {{ color: 'rgba(42, 46, 57, 0.5)' }},
            }},
            crosshair: {{
                mode: LightweightCharts.CrosshairMode.Normal,
            }},
            rightPriceScale: {{
                borderColor: 'rgba(197, 203, 206, 0.8)',
            }},
            timeScale: {{
                borderColor: 'rgba(197, 203, 206, 0.8)',
                timeVisible: true,
                secondsVisible: true,
            }},
        }});

        const candlestickSeries = chart.addCandlestickSeries({{
            upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
            wickUpColor: '#26a69a', wickDownColor: '#ef5350'
        }});

        const candleData = rawData.map(d => ({{
            time: d.time, open: d.open, high: d.high, low: d.low, close: d.close
        }}));
        candlestickSeries.setData(candleData);

        const strikeSeries = chart.addLineSeries({{
            color: '#ff9800',
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            title: 'Strike Level'
        }});
        strikeSeries.setData(rawData.map(d => ({{ time: d.time, value: d.strike }})));

        const requiredSpotSeries = chart.addLineSeries({{
            color: '#2962ff',
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Solid,
            title: 'Required TWAP Spot'
        }});
        requiredSpotSeries.setData(rawData.map(d => ({{ time: d.time, value: d.required_spot }})));

        const markers = [];
        rawData.forEach(d => {{
            if (d.signal === 'buy') {{
                markers.push({{
                    time: d.time,
                    position: 'belowBar',
                    color: '#26a69a',
                    shape: 'arrowUp',
                    text: 'BUY EDGE'
                }});
            }} else if (d.signal === 'sell') {{
                markers.push({{
                    time: d.time,
                    position: 'aboveBar',
                    color: '#ef5350',
                    shape: 'arrowDown',
                    text: 'SELL EDGE'
                }});
            }}
        }});
        candlestickSeries.setMarkers(markers);

        window.addEventListener('resize', () => {{
            chart.applyOptions({{ width: chartElement.clientWidth }});
        }});
    </script>
</body>
</html>
"""

    with open("generated/trading_chart.html", "w", encoding="utf-8") as f:
        f.write(html_template)


if __name__ == "__main__":
    print("Compiling data models and calculating execution thresholds...")
    market_data = generate_mock_arbitrage_data()
    build_chart_html(json.dumps(market_data))
    print("Success! Trading terminal generated inside 'generated/trading_chart.html'")
