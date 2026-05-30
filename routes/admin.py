import logging
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash
from utils.supabase_client import get_admin_supabase
from utils.helpers import admin_required

logger   = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__)


def _q(fn):
    """Run a Supabase query safely — return [] on any error."""
    try:
        res = fn()
        return res.data or []
    except Exception as e:
        logger.error(f'[Admin query] {e}')
        return []


@admin_bp.route('/')
@admin_required
def dashboard():
    try:
        db = get_admin_supabase()

        users        = _q(lambda: db.table('profiles').select('*').execute())
        deposits     = _q(lambda: db.table('deposits').select('*').order('created_at', desc=True).execute())
        withdrawals  = _q(lambda: db.table('withdrawals').select('*').order('created_at', desc=True).execute())
        transactions = _q(lambda: db.table('transactions').select('*').order('created_at', desc=True).limit(60).execute())
        investments  = _q(lambda: db.table('investments').select('*').order('created_at', desc=True).execute())
        actions      = _q(lambda: db.table('admin_actions').select('*').order('created_at', desc=True).limit(50).execute())

        user_map = {u['id']: u.get('username', '—') for u in users}

        # Pre-compute safe values to avoid Jinja2 filter crashes
        pending_deps  = [d for d in deposits    if d.get('status') == 'pending']
        pending_wds   = [w for w in withdrawals  if w.get('status') == 'pending']
        active_invs   = [i for i in investments  if i.get('status') == 'active']
        total_balance = sum(float(u.get('balance') or 0) for u in users)
        invested_vol  = sum(float(i.get('amount')  or 0) for i in active_invs)

        return render_template('admin.html',
            users=users,
            deposits=deposits,
            withdrawals=withdrawals,
            transactions=transactions,
            investments=investments,
            actions=actions,
            user_map=user_map,
            total_balance=total_balance,
            invested_vol=invested_vol,
            pending_deposits=pending_deps,
            pending_withdrawals=pending_wds,
            active_investments=active_invs,
        )

    except Exception as e:
        logger.exception(f'Admin dashboard error: {e}')
        return f'''<!DOCTYPE html>
<html><body style="font-family:sans-serif;background:#0b0c10;color:#e8eaf0;padding:2rem">
<div style="max-width:600px;margin:4rem auto;background:#14171f;border:1px solid #222633;border-radius:12px;padding:2rem">
  <div style="font-size:2rem;font-weight:800;color:#d4a843;margin-bottom:1rem">EDC Admin</div>
  <h2 style="color:#f87171">Dashboard Error</h2>
  <pre style="color:#9aa3b8;background:#0b0c10;padding:1rem;border-radius:8px;font-size:12px;
              white-space:pre-wrap;word-break:break-all">{type(e).__name__}: {e}</pre>
  <p style="color:#9aa3b8;font-size:13px">
    Check your Supabase SERVICE_KEY in Render environment variables.<br>
    Make sure all 6 database tables exist (run schema.sql in Supabase).
  </p>
  <a href="/auth/logout" style="color:#d4a843">← Logout</a>
</div></body></html>''', 500


@admin_bp.route('/deposit/<deposit_id>/<action>', methods=['POST'])
@admin_required
def handle_deposit(deposit_id, action):
    from routes.investments import pay_referral_commissions
    db  = get_admin_supabase()
    now = datetime.now(timezone.utc).isoformat()

    deps = _q(lambda: db.table('deposits').select('*').eq('id', deposit_id).execute())
    if not deps:
        flash('Deposit not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    dep    = deps[0]
    uid    = dep.get('user_id')
    amount = float(dep.get('amount') or 0)

    if action == 'approve':
        profs   = _q(lambda: db.table('profiles').select('balance').eq('id', uid).execute())
        balance = float(profs[0].get('balance') or 0) if profs else 0.0
        db.table('profiles').update({'balance': round(balance + amount, 2)}).eq('id', uid).execute()
        db.table('deposits').update({'status': 'approved', 'reviewed_at': now}).eq('id', deposit_id).execute()
        db.table('transactions').insert({
            'user_id': uid, 'type': 'deposit', 'amount': amount,
            'description': f'Deposit approved — ${amount} via {dep.get("network","N/A")}',
            'status': 'completed', 'created_at': now,
        }).execute()
        try:
            pay_referral_commissions(db, uid, amount, tx_type='deposit')
        except Exception as e:
            logger.error(f'Referral commission error: {e}')
        flash(f'Deposit of ${amount} approved and credited.', 'success')

    elif action == 'reject':
        db.table('deposits').update({'status': 'rejected', 'reviewed_at': now}).eq('id', deposit_id).execute()
        flash('Deposit rejected.', 'info')

    _log(db, f'{action}_deposit', deposit_id, f'{action} deposit #{deposit_id[:8]}', now)
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/withdrawal/<wd_id>/<action>', methods=['POST'])
@admin_required
def handle_withdrawal(wd_id, action):
    db  = get_admin_supabase()
    now = datetime.now(timezone.utc).isoformat()

    wds = _q(lambda: db.table('withdrawals').select('*').eq('id', wd_id).execute())
    if not wds:
        flash('Withdrawal not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    wd     = wds[0]
    uid    = wd.get('user_id')
    amount = float(wd.get('amount') or 0)

    if action == 'approve':
        profs   = _q(lambda: db.table('profiles').select('balance').eq('id', uid).execute())
        balance = float(profs[0].get('balance') or 0) if profs else 0.0
        db.table('profiles').update({'balance': round(max(balance - amount, 0), 2)}).eq('id', uid).execute()
        db.table('withdrawals').update({'status': 'approved', 'reviewed_at': now}).eq('id', wd_id).execute()
        db.table('transactions').insert({
            'user_id': uid, 'type': 'withdrawal', 'amount': -amount,
            'description': f'Withdrawal approved — ${amount}',
            'status': 'completed', 'created_at': now,
        }).execute()
        flash(f'Withdrawal of ${amount} approved.', 'success')

    elif action == 'reject':
        db.table('withdrawals').update({'status': 'rejected', 'reviewed_at': now}).eq('id', wd_id).execute()
        flash('Withdrawal rejected.', 'info')

    _log(db, f'{action}_withdrawal', wd_id, f'{action} withdrawal #{wd_id[:8]}', now)
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/adjust-balance', methods=['POST'])
@admin_required
def adjust_balance():
    db     = get_admin_supabase()
    now    = datetime.now(timezone.utc).isoformat()
    uid    = request.form.get('user_id', '')
    amount = float(request.form.get('amount', 0))
    reason = request.form.get('reason', 'Admin adjustment')

    profs = _q(lambda: db.table('profiles').select('balance').eq('id', uid).execute())
    if not profs:
        flash('User not found.', 'error')
        return redirect(url_for('admin.dashboard'))

    new_bal = round(float(profs[0].get('balance') or 0) + amount, 2)
    if new_bal < 0:
        flash('Balance cannot go negative.', 'error')
        return redirect(url_for('admin.dashboard'))

    db.table('profiles').update({'balance': new_bal}).eq('id', uid).execute()
    db.table('transactions').insert({
        'user_id': uid, 'type': 'admin_adjustment', 'amount': amount,
        'description': reason, 'status': 'completed', 'created_at': now,
    }).execute()
    _log(db, 'adjust_balance', uid, f'Adjusted ${amount} — {reason}', now)
    flash(f'Balance adjusted by ${amount}.', 'success')
    return redirect(url_for('admin.dashboard'))


def _log(db, action, target_id, details, now):
    try:
        db.table('admin_actions').insert({
            'admin_id': 'admin', 'action': action,
            'target_id': str(target_id), 'details': details,
            'created_at': now,
        }).execute()
    except Exception as e:
        logger.error(f'[Admin log] {e}')
