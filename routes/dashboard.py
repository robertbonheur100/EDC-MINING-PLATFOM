from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from config import Config
from utils.supabase_client import get_admin_supabase
from utils.helpers import login_required

dashboard_bp = Blueprint('dashboard', __name__)


# ─────────────────────────────────────────────
# DASHBOARD HOME
# ─────────────────────────────────────────────
@dashboard_bp.route('/')
@login_required
def index():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        profile_res = db.table('profiles').select('*').eq('id', uid).execute()
        profile = profile_res.data[0] if profile_res.data else {'username': 'User', 'balance': 0}

        deposits = db.table('deposits')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(20).execute().data or []

        withdrawals = db.table('withdrawals')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(20).execute().data or []

        investments = db.table('investments')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).execute().data or []

        transactions = db.table('transactions')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(30).execute().data or []

        l1_res   = db.table('profiles').select('id', count='exact').eq('referred_by', uid).execute()
        l1_count = getattr(l1_res, 'count', 0) or 0

        l2_res   = db.table('profiles').select('id', count='exact').eq('referred_by_l2', uid).execute()
        l2_count = getattr(l2_res, 'count', 0) or 0

        ref_earn = sum(
            t.get('amount', 0) for t in transactions
            if t.get('type') == 'referral_bonus'
        )

        return render_template('dashboard.html',
            profile=profile,
            deposits=deposits,
            withdrawals=withdrawals,
            investments=investments,
            transactions=transactions,
            l1_count=l1_count,
            l2_count=l2_count,
            referral_earnings=ref_earn,
            plans=Config.INVESTMENT_PLANS,
            usdt_trc20=Config.USDT_TRC20_ADDRESS,
            usdt_bep20=Config.USDT_BEP20_ADDRESS,
            whatsapp=Config.WHATSAPP_NUMBER,
        )

    except Exception as e:
        return f'<h2 style="font-family:sans-serif;padding:2rem">Dashboard error: {e}</h2>', 500


# ─────────────────────────────────────────────
# DEPOSIT
# ─────────────────────────────────────────────
@dashboard_bp.route('/deposit', methods=['POST'])
@login_required
def deposit():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount  = float(request.form.get('amount', 0))
        network = request.form.get('network', '')
        proof   = request.form.get('proof_note', '')

        if amount <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('dashboard.index'))

        db.table('deposits').insert({
            'user_id':    uid,
            'amount':     amount,
            'network':    network,
            'proof_note': proof,
            'status':     'pending',
            'created_at': datetime.now(timezone.utc).isoformat(),
        }).execute()

        flash('Deposit submitted! Send proof via WhatsApp to get approved.', 'success')

    except Exception as e:
        flash(f'Deposit error: {e}', 'error')

    return redirect(url_for('dashboard.index'))


# ─────────────────────────────────────────────
# WITHDRAW
# ─────────────────────────────────────────────
@dashboard_bp.route('/withdraw', methods=['POST'])
@login_required
def withdraw():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount  = float(request.form.get('amount', 0))
        wallet  = request.form.get('wallet_address', '').strip()
        network = request.form.get('network', '')

        profile_res = db.table('profiles').select('balance').eq('id', uid).execute()
        profile     = profile_res.data[0] if profile_res.data else {'balance': 0}
        balance     = profile.get('balance', 0)

        if amount <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('dashboard.index'))

        if amount > balance:
            flash('Insufficient balance.', 'error')
            return redirect(url_for('dashboard.index'))

        if not wallet:
            flash('Wallet address required.', 'error')
            return redirect(url_for('dashboard.index'))

        db.table('withdrawals').insert({
            'user_id':        uid,
            'amount':         amount,
            'wallet_address': wallet,
            'network':        network,
            'status':         'pending',
            'created_at':     datetime.now(timezone.utc).isoformat(),
        }).execute()

        flash('Withdrawal request submitted! Under review.', 'success')

    except Exception as e:
        flash(f'Withdrawal error: {e}', 'error')

    return redirect(url_for('dashboard.index'))
