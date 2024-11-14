import os
from dotenv import load_dotenv
import json
import logging
from datetime import datetime
import redis
import urllib3
import certifi
from flask import Flask, request, render_template
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

load_dotenv()
# initalize Flask app
app = Flask(__name__)
# logging message setting
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s- %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# env setting
redis_host = os.getenv("REDIS_HOST")
redis_port = os.getenv("REDIS_PORT")
redis_password = os.getenv("REDIS_PASSWORD")
API_KEY = os.getenv("API_KEY")

r = redis.Redis(
    host=redis_host,
    port=redis_port,
    password=redis_password,
    decode_responses=True)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "5 per minute"],
    storage_uri=f"redis://:{redis_password}@{redis_host}:{redis_port}/0"
)


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/weather")
def weather():
    location = request.args.get("location")
    city = request.args.get("city", "")
    date_start = request.args.get("start", "")
    date_end = request.args.get("end", "")
    daily_data = request.args.get("daily-data", "")

    try:
        # check if date range exceeds 15 days
        if date_start and date_end:
            today = datetime.now().date()
            end = datetime.strptime(date_end, "%Y-%m-%d").date()
            date_diff = end - today
            if date_diff.days > 14:
                raise ValueError(
                    "Date range exceeds the limit. Only forecasts for the next 15 days are available.")
        else:
            date_start = date_end = ""
    except ValueError as e:
        return render_template("Error.html", error=e)

    if daily_data:
        include = f"&include={daily_data}"
    else:
        include = daily_data
    if city:
        city = f"%2C{city}"

    redis_key = location + city + date_start + date_end + daily_data

    weather_data = r.get(redis_key)
    if weather_data:
        logging.info("Cache hit: Data retrieved from Redis")
        return json.loads(weather_data)

    else:
        try:
            # setting PoolManager instance
            http = urllib3.PoolManager(
                cert_reqs="CERT_REQUIRED",
                ca_certs=certifi.where()
            )
            WEATHER_URL = (f'https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/'
                           f'{location}{city}/{date_start}/{date_end}?unitGroup=metric{include}&key={API_KEY}&contentType=json')

            weather_data = http.request("GET", WEATHER_URL, timeout=5)

            if weather_data.status == 200:
                weather_data_decode = weather_data.data.decode('utf-8')
                r.set(redis_key, weather_data_decode, ex=3600)
                logging.info("Cache miss: Fetching data from API")
                return json.loads(weather_data_decode)
            elif weather_data.status == 400:
                logging.debug(f"API request failed with status {
                    weather_data.status}")
                error = "Weather API Error: Invalid location parameter value.."
                return render_template("Error.html", error=error)
            else:
                logging.debug(f"API request failed with status {
                    weather_data.status}")
                error = "Weather API Error "
                return render_template("Error.html", error=error)
        except urllib3.exceptions.HTTPError as e:
            logging.error(f"HTTP error occured: {e}")
            error = f"HTTP error occured: {e}"
            return render_template("Error.html", error=error)
        except urllib3.exceptions.TimeoutError as e:
            logging.error(f"Request timed out: {e}")
            error = f"Request timed out while trying to connect: {e}"
            return render_template("Error.html", error=error)
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
            error = "An unexpected error occurred while fetching weather data."
            return render_template("Error.html", error=error)


if __name__ == "__main__":
    app.run(debug=True, port=5500)
