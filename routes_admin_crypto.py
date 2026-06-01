"""
Admin Crypto routes — manage exchange rate, approve/reject buy/sell/HTG requests.
Attach these routes to the existing admin_bp or import as a separate blueprint.

Add to app.py:
    from routes.admin_crypto import admin_crypto_bp
    app.register_blueprint(admin_crypto_bp, url_prefix='/admin/crypto')
"""
import logging
from datetime import datetime, timezone
from flask import Blueprint, request, redirect, url_for, flash, render_template
from utils.supabase_client import get_admin_supabase
from utils.helpers import admin_required

logger          = logging.getLogger(__name__)
admin_crypto_bp = Blueprint('admin_crypto', __name__)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _q(fn):
    try:
        res = fn()
        return res.data or []
    except Exception as e:
        logger.error(f'[admin_crypto query] {e}')
        return []


def _log(db, action, target_id, details):
    try:
        db.table('admin_actions').insert({
            'admin_id':  'admin',
            'action':    action,
            'target_id': str(target_id),
            'details':   details,
            'created_at': _now(),
        }).execute()
    except Exception as e:
        logger.error(f'[admin_crypto log] {e}')


# ── Crypto Admin Dashboard ────────────────────────────────────────────────────

@admin_crypto_bp.route('/')
@admin_required
def dashboard():
    db = get_admin_supabase()

    users     = _q(lambda: db.table('profiles').select('id, username, balance_htg, balance_usdt').execute())
    buy_reqs  = _q(lambda: db.table('buy_crypto_requests').select('*').order('created_at', desc=True).execute())
    sell_reqs = _q(lambda: db.table('sell_crypto_requests').select('*').order('created_at', desc=True).execute())
    htg_wds   = _q(lambda: db.table('htg_withdrawals').select('*').order('created_at', desc=True).execute())
    rates     = _q(lambda: db.table('exchange_rates').select('*').order('created_at', desc=True).limit(10).execute())

    current_rate = float(rates[0]['rate']) if rates else 130.0
    user_map     = {u['id']: u.get('username', '—') for u in users}

    pending_buys  = [r for r in buy_reqs  if r.get('status') == 'pending']
    pending_sells = [r for r in sell_reqs if r.get('status') == 'pending']
    pending_wds   = [r for r in htg_wds   if r.get('status') == 'pending']

    return render_template('admin/crypto_dashboard.html',
        users=users,
        buy_reqs=buy_reqs,
        sell_reqs=sell_reqs,
        htg_wds=htg_wds,
        rates=rates,
        current_rate=current_rate,
        user_map=user_map,
        pending_buys=pending_buys,
        pending_sells=pending_sells,
        pending_wds=pending_wds,
    )


# ── Set Exchange Rate ─────────────────────────────────────────────────────────

@admin_crypto_bp.route('/set-rate', methods=['POST'])
@admin_required
def set_rate():
    db   = get_admin_supabase()
    rate = float(request.form.get('rate', 0))

    if rate <= 0:
        flash('Rate must be greater than zero.', 'error')
        return redirect(url_for('admin_crypto.dashboard'))

    db.table('exchange_rates').insert({
        'rate':       rate,
        'set_by':     'admin',
        'created_at': _now(),
    }).execute()

    _log(db, 'set_exchange_rate', 'rate', f'Exchange rate set to {rate} HTG/USDT')
    flash(f'Exchange rate updated to {rate} HTG per USDT.', 'success')
    return redirect(url_for('admin_crypto.dashboard'))


# ── Approve / Reject BUY request ─────────────────────────────────────────────

@admin_crypto_bp.route('/buy/<req_id>/<action>', methods=['POST'])
@admin_required
def handle_buy(req_id, action):
    db  = get_admin_supabase()
    now = _now()

    reqs = _q(lambda: db.table('buy_crypto_requests').select('*').eq('id', req_id).execute())
    if not reqs:
        flash('Buy request not found.', 'error')
        return redirect(url_for('admin_crypto.dashboard'))

    req        = reqs[0]
    uid        = req.get('user_id')
    amount_htg = float(req.get('amount_htg') or 0)

    if action == 'approve':
        profs   = _q(lambda: db.table('profiles').select('balance_htg').eq('id', uid).execute())
        bal_htg = float(profs[0].get('balance_htg') or 0) if profs else 0.0
        new_htg = round(bal_htg + amount_htg, 2)

        db.table('profiles').update({'balance_htg': new_htg}).eq('id', uid).execute()
        db.table('buy_crypto_requests').update({'status': 'approved', 'reviewed_at': now}).eq('id', req_id).execute()

        db.table('htg_transactions').insert({
            'user_id':     uid,
            'type':        'buy',
            'amount_htg':  amount_htg,
            'description': f'Buy request approved — {amount_htg} HTG credited via NatCash',
            'status':      'completed',
            'created_at':  now,
        }).execute()

        _log(db, 'approve_buy', req_id, f'Approved buy request #{req_id[:8]}: +{amount_htg} HTG')
        flash(f'Buy request approved. {amount_htg} HTG credited to user.', 'success')

    elif action == 'reject':
        db.table('buy_crypto_requests').update({'status': 'rejected', 'reviewed_at': now}).eq('id', req_id).execute()
        _log(db, 'reject_buy', req_id, f'Rejected buy request #{req_id[:8]}')
        flash('Buy request rejected.', 'info')

    return redirect(url_for('admin_crypto.dashboard'))


# ── Approve / Reject SELL request ────────────────────────────────────────────

@admin_crypto_bp.route('/sell/<req_id>/<action>', methods=['POST'])
@admin_required
def handle_sell(req_id, action):
    db  = get_admin_supabase()
    now = _now()

    reqs = _q(lambda: db.table('sell_crypto_requests').select('*').eq('id', req_id).execute())
    if not reqs:
        flash('Sell request not found.', 'error')
        return redirect(url_for('admin_crypto.dashboard'))

    req         = reqs[0]
    uid         = req.get('user_id')
    amount_usdt = float(req.get('amount_usdt') or 0)

    if action == 'approve':
        rate    = float(request.form.get('rate_used', 0)) or None
        if not rate:
            rates = _q(lambda: db.table('exchange_rates').select('rate').order('created_at', desc=True).limit(1).execute())
            rate  = float(rates[0]['rate']) if rates else 130.0

        amount_htg = round(amount_usdt * rate, 2)

        profs   = _q(lambda: db.table('profiles').select('balance_htg').eq('id', uid).execute())
        bal_htg = float(profs[0].get('balance_htg') or 0) if profs else 0.0
        new_htg = round(bal_htg + amount_htg, 2)

        db.table('profiles').update({'balance_htg': new_htg}).eq('id', uid).execute()
        db.table('sell_crypto_requests').update({'status': 'approved', 'reviewed_at': now}).eq('id', req_id).execute()

        db.table('htg_transactions').insert({
            'user_id':     uid,
            'type':        'sell',
            'amount_htg':  amount_htg,
            'amount_usdt': -amount_usdt,
            'rate':        rate,
            'description': f'Sell approved — {amount_usdt} USDT → {amount_htg} HTG @ {rate}',
            'status':      'completed',
            'created_at':  now,
        }).execute()

        _log(db, 'approve_sell', req_id, f'Approved sell #{req_id[:8]}: {amount_usdt} USDT → {amount_htg} HTG')
        flash(f'Sell request approved. {amount_htg} HTG credited to user.', 'success')

    elif action == 'reject':
        db.table('sell_crypto_requests').update({'status': 'rejected', 'reviewed_at': now}).eq('id', req_id).execute()
        _log(db, 'reject_sell', req_id, f'Rejected sell request #{req_id[:8]}')
        flash('Sell request rejected.', 'info')

    return redirect(url_for('admin_crypto.dashboard'))


# ── Approve / Reject HTG Withdrawal ──────────────────────────────────────────

@admin_crypto_bp.route('/htg-withdrawal/<wd_id>/<action>', methods=['POST'])
@admin_required
def handle_htg_withdrawal(wd_id, action):
    db  = get_admin_supabase()
    now = _now()

    wds = _q(lambda: db.table('htg_withdrawals').select('*').eq('id', wd_id).execute())
    if not wds:
        flash('HTG withdrawal not found.', 'error')
        return redirect(url_for('admin_crypto.dashboard'))

    wd         = wds[0]
    uid        = wd.get('user_id')
    amount_htg = float(wd.get('amount_htg') or 0)

    if action == 'approve':
        db.table('htg_withdrawals').update({'status': 'approved', 'reviewed_at': now}).eq('id', wd_id).execute()

        # Update the linked htg_transaction status
        try:
            db.table('htg_transactions')\
                .update({'status': 'completed'})\
                .eq('user_id', uid)\
                .eq('type', 'withdrawal_htg')\
                .eq('status', 'pending')\
                .execute()
        except Exception as e:
            logger.error(f'[htg_wd approve tx update] {e}')

        _log(db, 'approve_htg_withdrawal', wd_id, f'Approved HTG withdrawal #{wd_id[:8]}: {amount_htg} HTG')
        flash(f'HTG withdrawal of {amount_htg} HTG approved.', 'success')

    elif action == 'reject':
        # Refund the balance
        profs   = _q(lambda: db.table('profiles').select('balance_htg').eq('id', uid).execute())
        bal_htg = float(profs[0].get('balance_htg') or 0) if profs else 0.0
        new_htg = round(bal_htg + amount_htg, 2)
        db.table('profiles').update({'balance_htg': new_htg}).eq('id', uid).execute()
        db.table('htg_withdrawals').update({'status': 'rejected', 'reviewed_at': now}).eq('id', wd_id).execute()

        db.table('htg_transactions').insert({
            'user_id':     uid,
            'type':        'withdrawal_htg',
            'amount_htg':  amount_htg,
            'description': f'HTG withdrawal refunded (rejected) — {amount_htg} HTG',
            'status':      'completed',
            'created_at':  now,
        }).execute()

        _log(db, 'reject_htg_withdrawal', wd_id, f'Rejected HTG withdrawal #{wd_id[:8]}: refunded {amount_htg} HTG')
        flash(f'HTG withdrawal rejected. {amount_htg} HTG refunded to user.', 'info')

    return redirect(url_for('admin_crypto.dashboard'))


# ── Manual HTG Adjustment ─────────────────────────────────────────────────────

@admin_crypto_bp.route('/adjust-htg', methods=['POST'])
@admin_required
def adjust_htg():
    db         = get_admin_supabase()
    now        = _now()
    uid        = request.form.get('user_id', '')
    amount_htg = float(request.form.get('amount_htg', 0))
    reason     = request.form.get('reason', 'Admin HTG adjustment')

    profs = _q(lambda: db.table('profiles').select('balance_htg').eq('id', uid).execute())
    if not profs:
        flash('User not found.', 'error')
        return redirect(url_for('admin_crypto.dashboard'))

    new_htg = round(float(profs[0].get('balance_htg') or 0) + amount_htg, 2)
    if new_htg < 0:
        flash('Balance cannot go negative.', 'error')
        return redirect(url_for('admin_crypto.dashboard'))

    db.table('profiles').update({'balance_htg': new_htg}).eq('id', uid).execute()
    db.table('htg_transactions').insert({
        'user_id':     uid,
        'type':        'admin_adjustment',
        'amount_htg':  amount_htg,
        'description': reason,
        'status':      'completed',
        'created_at':  now,
    }).execute()

    _log(db, 'adjust_htg_balance', uid, f'Adjusted HTG {amount_htg:+.2f} — {reason}')
    flash(f'HTG balance adjusted by {amount_htg} HTG.', 'success')
    return redirect(url_for('admin_crypto.dashboard'))
