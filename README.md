# ICE Roulette Bot (Arabic)

Bot type: Channel giveaways/roulette, built with Python and aiogram 3, fully async, OOP modules.

Quick start

1) Create and fill `.env` from `.env.example`.
2) Install dependencies:
   - Python 3.11+
   - `pip install -r requirements.txt`
3) Start bot:
   - Polling: leave `WEBHOOK_URL` empty and run `python -m app`
   - Webhook: set `WEBHOOK_URL=https://your.domain` and run `python -m app`

Environment

- BOT_TOKEN: Telegram bot token
- BOT_CHANNEL: Bot service channel (for subscription gate)
- DATABASE_URL: e.g. `sqlite+aiosqlite:///./db.sqlite3` or Postgres URL
- REDIS_URL: optional, e.g. `redis://localhost:6379/0` for FSM and rate limiting
- WEBHOOK_URL: Base public https URL, e.g. `https://your.domain`
- WEBHOOK_PATH_TEMPLATE: Default `/webhook/{token}`
- WEBHOOK_SECRET: Optional Telegram secret token
- WEBAPP_HOST: Default `0.0.0.0`
- WEBAPP_PORT: Default `8080`

Folders

- `app/config.py` — settings loader
- `app/main.py` — bot startup (auto polling/webhook)
- `app/db/` — models and repositories
- `app/routers/` — message/callback routers and FSMs
- `app/keyboards/` — inline/reply keyboards
- `app/services/` — business logic (formatting, drawing, permissions)

Notes

- Webhook mode automatically sets webhook on startup and deletes it on shutdown.
- The bot supports thousands of simultaneous roulettes using efficient DB queries and idempotent joins.
- Winners are drawn with secrets.SystemRandom.

Webhook behind reverse proxy (Nginx example)

- Make sure your public URL is reachable and matches `WEBHOOK_URL`.
- Example Nginx location:

```
location /webhook/ {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Alembic migrations

- Initialize migrations: `alembic init -t async migrations`
- Configure `alembic.ini` to use `DATABASE_URL` env and target metadata from `app.db.models:Base.metadata`.
- Create revision: `alembic revision -m "init" --autogenerate`
- Upgrade: `alembic upgrade head`

Payments — Telegram Stars (XTR)

- The bot uses Telegram Stars for premium "gate channel" feature.
- Two tiers are available:
  - Monthly subscription: 100 XTR, extends access by 30 days.
  - One-time credit: 10 XTR, allows adding gates once.
- In the flow: when you choose to add a gate without entitlement, the bot shows a paywall with two buttons; tapping them opens the Telegram Stars payment sheet.
- After payment:
  - successful_payment event grants access immediately.
  - No payment success arrives if the user balance is insufficient (implicit refusal by Telegram).

Manual DB migrations

- Create/upgrade migrations:
  - `alembic upgrade head`
- New tables created:
  - `roulette_gates` (if not created yet)
  - `feature_access` (entitlements)
  - `purchases` (audit)

Manual testing

- Start the bot, link your channel, start create-roulette.
- After entering text, choose "إضافة قناة شرط"; if you have no access, the paywall appears.
- Try both buttons to see the Stars sheet. Complete payment to unlock.
- Add a gate and continue to winners → confirm; message in your channel should include the join button and optional gate links.

Admin and operations

- Set `ADMIN_IDS` in `.env` as comma-separated Telegram user IDs to enable admin commands.
- Admin commands (private chat with bot):
  - `/gate_status` — يعرض حالة الاستحقاق الحالية.
  - `/gate_grant_month` — يمنح اشتراك شهر (للاختبار/الدعم).
  - `/gate_grant_one` — يمنح رصيد استخدام واحد.
- A lightweight maintenance loop runs hourly to support future expiry/cleanup hooks.

Admin panel

- Use `/admin` from an admin account (ID must be in `ADMIN_IDS`) to open the panel.
- Buttons:
  - الاحصائيات: يعرض أرقام المستخدمين، القنوات، المجموعات، المدفوعين، الاشتراكات النشطة، وإجمالي النجوم.
  - الإذاعة: عنصر نائب سيتم تطويره لاحقاً.
  - تعيين قيمة الاشتراك: ضبط أسعار النجوم للمرة الواحدة والشهري.
  - تعيين قناة البوت الأساسية: تحديث القناة الرئيسية المستخدمة في التنويهات.

Deployment

- First-time deploy on a VPS:
  - `bash scripts/deploy.sh /opt/ro-bot`
  - Edit `/opt/ro-bot/.env` with production values if needed; the script created a systemd service `ro-bot.service` and ran DB migrations.
- Updating an existing deployment:
  - `bash scripts/update.sh /opt/ro-bot`
  - The script pulls latest code, installs dependencies, runs Alembic migrations safely, and restarts the service.
