# Halal Portfolio Alerts

Long-only, Sharia-screened alerts for halal US equities/ETFs, Sharia commodities and MSX stocks. This is not financial advice.

## What runs, and when
| Job | When | What you get |
|---|---|---|
| **Daily alerts** | 09:17 Muscat, every day | BUY/ACCUMULATE/HOLD/REDUCE/SELL/AVOID changes, MSX prices, portfolio checks, the monthly 100 OMR plan on the 1st, a weekly digest on Sunday |
| **Trade log** | Every 15 min | Reads trades you message to the Telegram bot and logs them to your private repo. Sends no alerts. |

Every alert goes to **Telegram**, which pushes to your phone instantly. There is no public dashboard: the website is turned off so your portfolio is only visible to you in Telegram. (An RSS file, `docs/feed.xml`, is still written with amounts masked; it's only reachable as a feed if GitHub Pages is switched back on.)

## Every alert tells you what to do with what *you* hold
Alerts are based on your trade log, so each one ends with an **ACTION**:
| Situation | Action you get |
|---|---|
| Signal turns REDUCE on something you hold | Sell about half: exact units and ≈OMR |
| Signal turns SELL | Sell all: units and ≈OMR |
| Signal turns AVOID (fails screening) | Exit fully, plus a reminder to give any impermissible gain to charity |
| BUY/ACCUMULATE, held or not | Buy the OMR amount from this month's plan (≈units) |
| SELL/REDUCE/AVOID on something you **don't** hold | No alert: nothing to do |
| Holding up ≥30% **and** over its limit or its domain overweight | 💰 Take profit: sell enough to get back to target (never more than half) |
| Holding over 35% but gain under 30% | No sale; new money goes elsewhere |
| Holding down ≥15% | Depends on its signal: average down (still ACCUMULATE), hold (HOLD), or exit with the loss amount (REDUCE/SELL) |
| Domain under or over target | Where this month's money goes; no forced selling |

Privacy: the public feed and dashboard show the action with units and amounts hidden (•••). **Telegram gets the full version.** Private text is never saved to the public repo.

## Signal meanings
- 🟢 **BUY**: strong. Gets double weight in the monthly plan.
- 🟩 **ACCUMULATE**: positive. Buy gradually; a smaller share each month.
- ⚪ **HOLD**: keep what you have; no new money.
- 🟧 **REDUCE**: trend broken; consider trimming.
- 🔴 **SELL**: exit candidate.
- ⛔ **AVOID**: fails screening; never buy.

There is no SHORT signal: shorting and leverage aren't Sharia-compliant.

## How the portfolio monitor works
1. **You log each trade** as one line in `transactions.csv` in your *private* repo `halal-portfolio`. You can do this from the GitHub app on your phone.
2. **Every morning** the system reads that file and fetches today's price for each holding (Yahoo for US and gold, Mubasher for MSX). It values everything in OMR.
3. **The dashboard** shows:
   - total value, amount invested, and profit or loss;
   - each domain's weight against its target (US 59 / Commodities 18 / MSX 23);
   - every holding with its profit or loss.
4. **It alerts you when:**
   - a domain is 10 or more points off its target;
   - one holding is 35% or more of the portfolio;
   - a holding is down 15% or more from what you paid.
5. **The monthly plan** on the 1st sends more of the 100 OMR to underweight domains, so the portfolio rebalances without selling.

## Log trades through Telegram
Message your bot. It's processed within about 15 minutes and the bot replies to confirm:
```
bought 100 OQGN at 0.217 fee 0.4
sold 2 SPUS at 61.2 fee 1
buy 1.5 SPUS @ 59.9 fee 1 on 2026-11-02
```
Price and fee are in the instrument's currency: MSX = OMR, US and gold = USD, 9405 = SAR. Fee and date are optional. You can still log a sale of an old holding that is no longer on the watchlist.
Commands: `/last` (last 5 trades), `/undo` (remove the last Telegram-logged trade), `/pos` (positions), `/help`.
Only messages from your own chat are accepted. Sells larger than your position are rejected (no short selling).
This needs `PORTFOLIO_TOKEN` to have **Contents: Read and write** on `halal-portfolio`.

## MSX prices
Each morning the job reads each MSX stock's price from its Mubasher page (`english.mubasher.info/markets/MSM/stocks/<TICKER>`, 15 minutes delayed). It saves the prices to `state/price_history.csv`, building its own history because no free MSX history source exists.

- **Weeks 1–2:** MSX signals use the research view. Price and profit or loss are live.
- **After about 10 weeks:** the 50-day trend and RSI kick in.
- **After about 10 months:** the full 200-day trend kicks in.
- **If a fetch fails:** you get a 🛠️ alert. Add that day's close to `manual_prices.csv` in your private repo.

## Setup (about 15 minutes, all free)
1. **Public repo `halal-alerts`:** upload this folder, including `.github/`. It must be public so GitHub Actions minutes are unlimited and the free Pages site works. Your trades never go in it.
2. **Private repo `halal-portfolio`:** upload the files from the `halal-portfolio` folder.
3. **Token so the public repo can read the private one:** GitHub → Settings → Developer settings → Fine-grained tokens → Generate. Choose *Only select repositories → halal-portfolio* and set *Contents: Read-only*. Copy the token.
4. **Telegram bot:**
   - In Telegram, message **@BotFather** and send `/newbot`. Copy the token it gives you.
   - Send any message to your new bot.
   - Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy `chat.id`.
5. **Secrets:** in `halal-alerts`, go to Settings → Secrets and variables → Actions and add:
   - `PORTFOLIO_TOKEN`: the token from step 3
   - `TELEGRAM_BOT_TOKEN`: the bot token from step 4
   - `TELEGRAM_CHAT_ID`: the chat ID from step 4
6. **Pages (off):** leave GitHub Pages unpublished; the site would be public on a free plan.
7. **First run:** Actions → *daily-alerts* → **Run workflow**. Also run *trade-log* once. Your first Telegram alerts should arrive within a minute.
8. **iPhone:**
   - Telegram notifications are on by default.

## iPhone home-screen widget (private)
Charts on your home screen, with full OMR amounts, read from your **private** `halal-portfolio` repo. The daily job writes `widget.json` there. It never goes to this public repo.

1. Install **Scriptable** (free) from the App Store.
2. Create a GitHub token: github.com → Settings → Developer settings → Fine-grained tokens → *Generate new token*. Repository access: **Only select repositories → halal-portfolio**. Permissions: **Contents: Read-only**. Copy it.
3. In Scriptable tap **+**, paste [`widget/HalalPortfolio.js`](widget/HalalPortfolio.js), name it *Halal Portfolio*, and run it once. Paste the token when asked (kept in the iPhone Keychain).
4. Long-press the home screen → **+** → Scriptable → pick a size → *Edit Widget* → Script: **Halal Portfolio**.

Small: value + chart. Medium: adds allocation vs target. Large: adds holdings with 30-day sparklines.

## Tuning (`config/settings.json`)
- Budget and targets: `monthly_budget_omr`, `targets_pct`
- Portfolio alerts: `drift_alert_pp`, `max_position_pct`, `loss_alert_pct`, `take_profit_pct`
- Privacy: `privacy_mode: true` hides OMR amounts in the public repo's feed file. Telegram messages are private, but amounts are hidden there too.

## Files
- `config/watchlist.json`: instruments, research views and compliance notes (refresh monthly)
- `research/*.json`: the research desk's raw findings
- `src/run.py`: daily job
- `src/trade_bot.py`: 15-minute Telegram trade logger
- `src/signals.py`, `portfolio.py`, `prices.py`, `feed.py`, `notify.py`: signal, portfolio, price, feed and notification code
- `state/`: signal memory, alert history and MSX price history (committed by the bot)

To test offline: `OFFLINE_SAMPLE=1 python src/run.py`
