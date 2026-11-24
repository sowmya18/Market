# Get your own link (free, about 15 minutes)

You need two free accounts: **GitHub** (stores the code and runs the schedule) and
**Streamlit Community Cloud** (hosts the web app and gives you the link).

## 1. Put the code on GitHub
1. Sign up at https://github.com, then click **New repository** and name it `nifty-agent`.
   Choose **Private** if you don't want others to see it.
2. On the new repo page click **uploading an existing file**, then drag in everything from the unzipped
   `nifty_agent` folder: `app.py`, `agent.py`, `config.py`, `data.py`, `indicators.py`,
   `global_markets.py`, `strategies.py`, `requirements.txt`, `README.md`, `DEPLOY.md`.
   Click **Commit changes**.
3. Add the schedule file. Folders starting with a dot are often hidden, so create it by hand:
   **Add file → Create new file**, type the name `.github/workflows/schedule.yml`, paste in the
   contents of that file from the zip, and click **Commit changes**.
4. **Settings → Actions → General → Workflow permissions** → select **Read and write permissions** → Save.
   This lets the schedule save each report back into the repo.

## 2. Turn on the daily schedule
5. Open the **Actions** tab, click **Nifty agent schedule**, then **Run workflow** to test it now.
   After about 2 minutes a `reports/` folder with the first report appears in the repo.
6. From then on it runs automatically, Monday to Friday, at
   **08:50, 09:35, 11:30, 13:45 and 15:45 IST**, downloading fresh prices every time.
   GitHub can start scheduled runs 5–15 minutes late when it is busy. To change the times, edit the
   `cron` lines (they are in UTC: IST minus 5 h 30 min).

## 3. Get the web link
7. Go to https://share.streamlit.io, sign in **with GitHub** and click **Create app**.
8. Pick your `nifty-agent` repo, branch `main`, main file `app.py`. Under **App URL** choose a name,
   e.g. `pranav-nifty-agent`. Click **Deploy**.
9. After 2–3 minutes your app is live at **https://pranav-nifty-agent.streamlit.app**.
   Bookmark it, or add it to your phone's home screen.

## How "always latest" works
- Every time you open the app, press **▶ Run agent now**, or a scheduled time arrives while the page
  is open, it downloads the latest prices. Nothing is reused from an earlier run.
- While the page is open it also refreshes every 15 minutes during market hours (adjustable in the sidebar).
- When the page is closed, GitHub still runs the agent at the five times above. Those reports
  appear in the app's **📁 Scheduled reports** tab.
- A free Streamlit app goes to sleep after a few days without visitors. Opening the link wakes it
  in about 30 seconds.

## Optional: phone alerts on Telegram
In Telegram, message **@BotFather**, send `/newbot` and copy the token. Then message your new bot once
and open `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat id.
In GitHub: **Settings → Secrets and variables → Actions → New repository secret**. Add
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Each scheduled run will then send the top picks to your phone.

## Run on your own computer instead
```bash
pip install -r requirements.txt
streamlit run app.py        # opens http://localhost:8501
```
