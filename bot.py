# Import required libraries
from flask import Flask, request                      # This library helps us create a web server and handle incoming HTTP requests
from coinbase.rest import RESTClient                  # This library allows us to interact with Coinbase's trading API
from datetime import datetime                         # This helps us get the current date and time for timestamps
import uuid                                           # This generates unique IDs to identify each order
import os                                             # This helps us work with files and check if files exist
import json                                           # This lets us read and write JSON files, useful for storing API keys
from decimal import Decimal, ROUND_DOWN               # This allows us to do precise decimal math and round down numbers

# === CONFIGURATION ===
DEBUG = True                                          # This turns on/off debug messages to help us see what's happening
API_KEY_FILE = "/opt/coinbase-bot/cdp_api_key.json"  # This is the file path where our API credentials are stored
OPEN_LOG = "/opt/coinbase-bot/OPEN.log"              # This file keeps track of trades that are currently open
CLOSE_LOG = "/opt/coinbase-bot/CLOSE.log"            # This file keeps track of trades that have been closed
SERVER_LOG = "/opt/coinbase-bot/server_output.txt"   # This file logs general events and errors from the server
WEBHOOK_SECRET = "SUPER_SECRET_KEY"                  # This defines the secret key that must be provided in the URL
MAX_POSITION_SIZE = 0.05                             # This sets the maximum portion of our USD balance to use per trade (5%)

# === LOGGING UTILITY FUNCTIONS ===
def log_debug(message):
    """Logs debug messages when DEBUG is True."""
    if DEBUG:
        # Open the server log file in append mode and write a debug message with a timestamp
        with open(SERVER_LOG, "a") as f:
            f.write(f"[DEBUG] {datetime.utcnow().isoformat()} - {message}\n")

def log_event(message):
    """Logs normal operational events."""
    # Open the server log file and write an event message with a timestamp
    with open(SERVER_LOG, "a") as f:
        f.write(f"[EVENT] {datetime.utcnow().isoformat()} - {message}\n")

def log_error(message):
    """Logs error messages."""
    # Open the server log file and write an error message with a timestamp
    with open(SERVER_LOG, "a") as f:
        f.write(f"[ERROR] {datetime.utcnow().isoformat()} - {message}\n")

# === INIT COINBASE CLIENT ===
try:
    # Try to open the API key file and load the credentials
    with open(API_KEY_FILE, "r") as f:
        creds = json.load(f)
        API_KEY = creds["name"]          # Get the API key from the JSON data
        API_SECRET = creds["privateKey"] # Get the secret key from the JSON data
except Exception as e:
    # If loading fails, log the error and stop the program
    log_error(f"Failed to load API key JSON: {e}")
    raise SystemExit("Could not load credentials")

# Initialize Coinbase client with the API keys so we can make trades
client = RESTClient(api_key=API_KEY, api_secret=API_SECRET)
# Create a Flask app instance which will handle incoming web requests
app = Flask(__name__)

# === TRADE LOGGING FUNCTIONS ===
def log_open(id, symbol, qty, price):
    """Logs an open trade to OPEN.log."""
    # Get the current UTC datetime and remove colons for file compatibility
    dt = datetime.utcnow().isoformat().replace(":", "")
    # Format a string to record the open trade details
    line = f"OPEN::{id}:{dt}:{symbol}:{qty}:{price}:\n"
    # Append this line to the OPEN log file
    with open(OPEN_LOG, "a") as f:
        f.write(line)

def log_close(id, symbol, qty, price, pnl):
    """Logs a closed trade to CLOSE.log."""
    # Get current datetime in ISO format for timestamp
    dt = datetime.utcnow().isoformat()
    # Format a string with the closed trade details including profit/loss
    line = f"CLOSE::{id}:{dt}:{symbol}:{qty}:{price}:{pnl}\n"
    # Append this line to the CLOSE log file
    with open(CLOSE_LOG, "a") as f:
        f.write(line)

def find_open_trade(symbol):
    """Looks for an existing open trade for the given symbol."""
    # If the OPEN log file doesn't exist, return None (no open trades)
    if not os.path.exists(OPEN_LOG):
        return None
    # Read through each line in the OPEN log file
    with open(OPEN_LOG, "r") as f:
        for line in f:
            # If the symbol is found in the line, return the line (open trade found)
            if f":{symbol}:" in line:
                return line.strip().rstrip(":")
    # If no matching line is found, return None
    return None

def remove_open_trade(symbol):
    """Removes a line from OPEN.log corresponding to the symbol."""
    # If the OPEN log file doesn't exist, do nothing
    if not os.path.exists(OPEN_LOG):
        return
    # Read all lines from the OPEN log file
    lines = open(OPEN_LOG).readlines()
    # Open the OPEN log file in write mode to overwrite it
    with open(OPEN_LOG, "w") as f:
        for line in lines:
            # Write back only the lines that do NOT contain the symbol (removes the matching trade)
            if f":{symbol}:" not in line:
                f.write(line)

# === MAIN WEBHOOK ENTRYPOINT ===
@app.route("/", methods=["POST"])
def webhook():
    # Check for existence of webhook secret
    data = request.get_data(as_text=True).strip().upper()
    if request.args.get("secret") != WEBHOOK_SECRET:
        log_error("Unauthorized webhook access attempt")
        return "Forbidden", 403
    log_event(f"Webhook received data: {data}")
    """Webhook endpoint to handle BUY and SELL alerts from TradingView."""
    # Get the raw data sent in the HTTP POST request and convert it to uppercase text
    data = request.get_data(as_text=True).strip().upper()
    # Log that we received data from the webhook
    log_event(f"Webhook received data: {data}")

    # If the data is "PING", respond with "pong" to confirm the server is alive
    if data == "PING":
        return "pong", 200  # Basic health check

    # Try to split the incoming data into an action (BUY/SELL) and a trading symbol (e.g. BTC-USD)
    try:
        action, symbol = data.split()
        # Split the symbol into base and quote currencies (e.g. BTC and USD)
        base_currency, quote_currency = symbol.split("-")
        # Log the parsed action and symbol for debugging
        log_debug(f"Parsed action: {action}, symbol: {symbol}")
    except Exception as e:
        # If the input format is wrong, log an error and return a bad request response
        log_error(f"Invalid input format: {e}")
        return "Bad format", 400

    def get_precision(symbol):
        """Get the correct decimal precision for a trading pair."""
        try:
            # Ask Coinbase API for product details to find the smallest unit increment for the base currency
            product = client.get_product(symbol)
            base_increment = product["base_increment"]
            # Calculate how many decimal places are used (e.g. 0.0001 means 4 decimal places)
            return abs(Decimal(base_increment).as_tuple().exponent)
        except Exception as e:
            # If fetching precision fails, log error and return default precision of 8 decimals
            log_error(f"Failed to fetch precision for {symbol}: {e}")
            return 8  # default fallback precision

    try:
        # Get all account balances from Coinbase
        accounts = client.get_accounts()
        # Log all account currencies for debugging
        log_debug(f"Account currencies: {[a.currency for a in accounts.accounts]}")
        # Find the USD account from the list of accounts
        usd_account = next(
            (a for a in accounts["accounts"] if a["currency"] == "USD"), None
        )
        # If no USD account is found, log error and return server error
        if not usd_account:
            log_error("No USD balance found")
            return "No USD balance found", 500

        # Extract the available USD balance as a float
        usd_balance = float(usd_account["available_balance"]["value"])
        # Log the USD balance for debugging
        log_debug(f"USD available balance: {usd_balance}")

        # === BUY HANDLER ===
        if action == "BUY":
            # Check if we already have an open position for this symbol
            if find_open_trade(symbol):
                # If yes, we don't open another one; just return a message
                return "Position already open", 200

            # Fetch the current product info to get the current price
            product = client.get_product(symbol)
            price = float(product["price"])
            # Log the fetched price for debugging
            log_debug(f"Fetched price for {symbol}: {price}")

            # Calculate how much USD we want to use for this trade (max 5% of balance)
            size_usd = usd_balance * MAX_POSITION_SIZE
            # Get the decimal precision for the trading pair
            precision = get_precision(symbol)
            # Calculate the quantity of base currency to buy (USD amount divided by price)
            raw_qty = Decimal(size_usd) / Decimal(price)
            # Round down the quantity to the correct precision to avoid errors
            qty = raw_qty.quantize(Decimal(10) ** -precision, rounding=ROUND_DOWN)
            # Log the calculated quantity
            log_debug(f"Calculated BUY quantity: {qty}")

            # Place a market buy order on Coinbase with the calculated quantity
            order = client.create_order(
                client_order_id=str(uuid.uuid4()),  # Unique ID for this order
                product_id=symbol,                  # Trading pair symbol
                side=action.upper(),                # BUY side
                order_configuration={"market_market_ioc": {"base_size": str(qty)}},  # Market order with immediate-or-cancel
            )
            # Log the order details for debugging
            log_debug(f"Market BUY order placed: {order.__dict__}")

            # Generate a short unique ID for logging this trade
            id = str(uuid.uuid4())[:8]
            # Log the open trade details to the OPEN log file
            log_open(id, symbol, qty, price)
            # Log the event of executing a BUY
            log_event(f"BUY executed for {symbol} - {qty} @ {price}")
            # Return a success message
            return f"BUY executed: {symbol} - {qty} @ {price}", 200

        # === SELL HANDLER ===
        elif action == "SELL":
            # Look for an open trade for this symbol to close
            open_line = find_open_trade(symbol)
            # If no open trade is found, return a message saying so
            if not open_line:
                return "No open position", 200

            # Log the open trade line for debugging
            log_debug(f"Parsing open_line: {open_line}")
            try:
                # Remove trailing colon if present
                if open_line.endswith(":"):
                    open_line = open_line[:-1]

                # Split the open line into prefix and the rest of the data
                prefix, remainder = open_line.split("::", 1)
                # Split the remainder into its parts: id, timestamp, symbol, quantity, entry price
                parts = remainder.split(":")
                # Check that we have exactly 5 parts, otherwise raise an error
                if len(parts) != 5:
                    raise ValueError("OPEN line does not contain exactly 5 parts")
                # Assign each part to a variable
                id, timestamp, symbol, qty, entry_price = parts
                # Convert qty and entry_price to floats for calculations
                qty = float(qty)
                entry_price = float(entry_price)
            except Exception as ve:
                # If parsing fails, log the error and return server error
                log_error(f"Bad OPEN log format or parsing error: {open_line} - {ve}")
                return "Bad log format", 500

            # Fetch current price for the symbol from Coinbase
            product = client.get_product(symbol)
            price = float(product["price"])
            # Log the fetched price for SELL
            log_debug(f"Fetched price for SELL: {price}")

            # Place a market sell order for the quantity we bought earlier
            order = client.create_order(
                client_order_id=str(uuid.uuid4()),  # Unique ID for this order
                product_id=symbol,                  # Trading pair symbol
                side=action.upper(),                # SELL side
                order_configuration={"market_market_ioc": {"base_size": str(qty)}},  # Market order with immediate-or-cancel
            )
            # Log the order details for debugging
            log_debug(f"Market SELL order placed: {order.__dict__}")

            # Calculate profit or loss as (sell price - buy price) * quantity
            pnl = round((price - entry_price) * qty, 2)
            # Remove the open trade from the OPEN log since it is now closed
            remove_open_trade(symbol)
            # Log the closed trade with profit/loss to the CLOSE log file
            log_close(id, symbol, qty, price, pnl)
            # Log the event of executing a SELL with P/L info
            log_event(f"SELL executed for {symbol} - {qty} @ {price} (P/L: {pnl})")
            # Return a success message with P/L info
            return f"SELL executed: {symbol} - {qty} @ {price} (P/L: {pnl})", 200

        else:
            # If the action is not BUY or SELL, log an error and return a bad request response
            log_error(f"Unknown action received: {action}")
            return "Unknown command", 400

    except Exception as e:
        # Catch any other unexpected errors, log them, and return a server error response
        log_error(f"Internal Error: {str(e)}")
        return f"Internal Error: {str(e)}", 500

# === START SERVER ===
if __name__ == "__main__":
    # Log that the server is starting
    log_event("Starting Flask server...")
    # Print to console that the server is starting
    print("Starting Flask server...")
    # Run the Flask server to listen on all network interfaces on port 80
    app.run(host="0.0.0.0", port=80)  # Listens on all network interfaces