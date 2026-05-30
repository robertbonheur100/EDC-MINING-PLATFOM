# EDC — Elite Digital Capital
## Crypto Investment Platform (v2 — Standard Blueprint Architecture)

---

## Project Structure

```
project/
│
├── app.py                  ← Flask factory + blueprint registration
├── config.py               ← All settings (reads .env)
├── scheduler.py            ← APScheduler daily profit background job
├── requirements.txt
├── render.yaml             ← Render.com deployment config
├── schema.sql              ← Run once in Supabase SQL Editor
├── .env                    ← Your secrets (never commit this)
│
├── routes/
│   ├── __init__.py
│   ├── auth.py             ← /auth/login, /auth/register, /auth/logout
│   ├── dashboard.py        ← /dashboard/, /dashboard/deposit, /dashboard/withdraw
│   ├── admin.py            ← /admin/ (full admin panel)
│   ├── investments.py      ← /investments/activate + referral engine
│   └── referrals.py        ← /referrals/ (referral stats)
│
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── referrals.html
│   └── admin.html
│
├── static/
│   ├── css/main.css
│   ├── js/main.js
│   └── images/
│
└── utils/
    ├── __init__.py
    ├── supabase_client.py  ← get_supabase() + get_admin_supabase()
    └── helpers.py          ← hash_password, login_required, admin_required
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env .env.local   # edit with your real values

# 3. Run schema in Supabase SQL Editor (once)
# Copy schema.sql → paste in Supabase → SQL Editor → Run

# 4. Development
python app.py

# 5. Production
gunicorn app:app --workers 2 --bind 0.0.0.0:5000
```

---

## Deploy to Render

1. Push this folder to a GitHub repo
2. Go to [render.com](https://render.com) → New Web Service → connect repo
3. Render auto-detects `render.yaml`
4. Set environment variables in Render dashboard:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_KEY`
   - `ADMIN_EMAIL`
   - `ADMIN_PASSWORD`
5. Deploy ✓

---

## Admin Access
- URL: `/admin/`
- Credentials set via `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `.env`

## Deposit Wallets
| Network | Address |
|---------|---------|
| USDT TRC-20 | `TNjKythwpkcPQo5XwckeBC4ZyeKZf7HaJ2` |
| USDT BEP-20 | `0x2ba88a4d6cabaded5d06c75ef3b3efec386acaef` |

WhatsApp proof: **+50941727986**

## Plans & Earnings
| Plan | Amount | Daily (2%) |
|------|--------|-----------|
| Starter | $50 | $1/day |
| Basic | $100 | $2/day |
| Pro | $500 | $10/day |
| Elite | $1000 | $20/day |
