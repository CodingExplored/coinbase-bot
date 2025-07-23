

# Coinbase TradingView Webhook Bot

A lightweight Python-based webhook listener that executes spot trades on Coinbase in response to TradingView alerts.

---

## 🖥️ Setup on Ubuntu Droplet

### 1. 📁 Create Bot Directory

```bash
mkdir /opt/coinbase-bot && cd /opt/coinbase-bot
nano bot.py
```

Paste your `bot.py` content inside the nano editor and save the file.

---

### 2. 🔧 Install Required Software

```bash
apt update && apt install -y python3-pip git nano
pip3 install flask requests
pip install git+https://github.com/coinbase/coinbase-advanced-py.git
```

---

### 3. ⬆️ Transfer Your Bot Files

Move your local `bot.py` (and any credentials/config files) to the `/opt/coinbase-bot` directory.

---

### 4. ⚙️ Create systemd Service

Create a service file:

```bash
nano /etc/systemd/system/coinbase-bot.service
```

Paste the following:

```ini
[Unit]
Description=Coinbase TradingView Webhook Bot
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/coinbase-bot/bot.py
WorkingDirectory=/opt/coinbase-bot
Restart=always
User=root

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable coinbase-bot
sudo systemctl start coinbase-bot
```

To verify it's running:

```bash
sudo systemctl status coinbase-bot
```

---

### 5. 🔁 Test the Bot

```bash
curl -X POST "http://161.35.101.95/?secret=c91f7de31b78462e9e99db41545cd08a" \
-H "Content-Type: text/plain" -d "PING"
```

Expected response: `PONG`

---

## 📌 Notes

- Make sure the secret in the request matches the one your bot expects.
- Store your API keys securely (e.g., `/opt/coinbase-bot/cdp_api_key.json`).
- Log bot activity and trade events for transparency and troubleshooting.