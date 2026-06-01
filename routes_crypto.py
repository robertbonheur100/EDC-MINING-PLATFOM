"""
Crypto blueprint — Buy Crypto, Sell Crypto, Convert HTG↔USDT, HTG Wallet.
URL prefix: /crypto
"""
import logging
from datetime import datetime, timezone
from flask import Blueprint, request, redirect, url_for, session, flash, render_template
from config import Config
from utils.supabase_client import get_admin_supabase
from utils.helpers import login_required

logger    = logging.getLogger(__name__)
crypto_bp = Blueprint('crypto', __name__)

NATCASH_NUMBER = '41727986'  # Admin NatCash number


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_rate(db) -> float:
    """Return the latest admin-set exchange rate (HTG per 1 USDT)."""
    try:
        res = db.table('exchange_rates').select('rate').order('created_at', desc=True).limit(1).execute()
        if res.data:
            return float(res.data[0]['rate'])
    except Exception as e:
        logger.error(f'[get_rate] {e}')
    return 130.0  # safe default


def _get_profile(db, uid):
    try:
        res = db.table('profiles').select('*').eq('id', uid).execute()
        return res.data[0] if res.data else {}
    except Exception as e:
        logger.error(f'[get_profile] {e}')
        return {}


def _now():
    return datetime.now(timezone.utc).isoformat()


# ── HTG Wallet overview ───────────────────────────────────────────────────────

@crypto_bp.route('/htg-wallet')
@login_required
def htg_wallet():
    db      = get_admin_supabase()
    uid     = session['user_id']
    profile = _get_profile(db, uid)
    rate    = _get_rate(db)

    try:
        htg_txs = db.table('htg_transactions')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(40).execute().data or []
        buy_reqs = db.table('buy_crypto_requests')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(20).execute().data or []
        sell_reqs = db.table('sell_crypto_requests')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(20).execute().data or []
        htg_wds = db.table('htg_withdrawals')\
            .select('*').eq('user_id', uid)\
            .order('created_at', desc=True).limit(20).execute().data or []
    except Exception as e:
        logger.error(f'[htg_wallet] {e}')
        htg_txs = buy_reqs = sell_reqs = htg_wds = []

    return render_template('crypto/htg_wallet.html',
        profile=profile,
        rate=rate,
        htg_txs=htg_txs,
        buy_reqs=buy_reqs,
        sell_reqs=sell_reqs,
        htg_wds=htg_wds,
        natcash_number=NATCASH_NUMBER,
        usdt_trc20=Config.USDT_TRC20_ADDRESS,
        usdt_bep20=Config.USDT_BEP20_ADDRESS,
    )


# ── BUY CRYPTO (HTG → USDT via NatCash) ──────────────────────────────────────

@crypto_bp.route('/buy', methods=['POST'])
@login_required
def buy_crypto():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount_htg     = float(request.form.get('amount_htg', 0))
        natcash_sender = request.form.get('natcash_sender', '').strip()
        proof_note     = request.form.get('proof_note', '').strip()

        if amount_htg <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('crypto.htg_wallet'))

        if not natcash_sender:
            flash('Please provide your NatCash sender number.', 'error')
            return redirect(url_for('crypto.htg_wallet'))

        db.table('buy_crypto_requests').insert({
            'user_id':        uid,
            'amount_htg':     amount_htg,
            'natcash_sender': natcash_sender,
            'proof_note':     proof_note,
            'status':         'pending',
            'created_at':     _now(),
        }).execute()

        flash('Buy request submitted! Admin will approve after confirming NatCash payment.', 'success')

    except Exception as e:
        logger.error(f'[buy_crypto] {e}')
        flash(f'Error submitting buy request: {e}', 'error')

    return redirect(url_for('crypto.htg_wallet'))


# ── SELL CRYPTO (USDT → HTG via NatCash) ─────────────────────────────────────

@crypto_bp.route('/sell', methods=['POST'])
@login_required
def sell_crypto():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount_usdt      = float(request.form.get('amount_usdt', 0))
        tx_hash          = request.form.get('tx_hash', '').strip()
        network          = request.form.get('network', 'TRC-20')
        natcash_receiver = request.form.get('natcash_receiver', '').strip()

        if amount_usdt <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('crypto.htg_wallet'))

        if not natcash_receiver:
            flash('Please provide your NatCash phone number.', 'error')
            return redirect(url_for('crypto.htg_wallet'))

        if not tx_hash:
            flash('Please provide the transaction hash.', 'error')
            return redirect(url_for('crypto.htg_wallet'))

        db.table('sell_crypto_requests').insert({
            'user_id':          uid,
            'amount_usdt':      amount_usdt,
            'tx_hash':          tx_hash,
            'network':          network,
            'natcash_receiver': natcash_receiver,
            'status':           'pending',
            'created_at':       _now(),
        }).execute()

        flash('Sell request submitted! Admin will send HTG to your NatCash after verifying the transaction.', 'success')

    except Exception as e:
        logger.error(f'[sell_crypto] {e}')
        flash(f'Error submitting sell request: {e}', 'error')

    return redirect(url_for('crypto.htg_wallet'))


# ── CONVERT HTG → USDT ───────────────────────────────────────────────────────

@crypto_bp.route('/convert-htg-to-usdt', methods=['POST'])
@login_required
def convert_htg_to_usdt():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount_htg = float(request.form.get('amount_htg', 0))
        if amount_htg <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('crypto.htg_wallet'))

        profile = _get_profile(db, uid)
        bal_htg = float(profile.get('balance_htg') or 0)

        if amount_htg > bal_htg:
            flash('Insufficient HTG balance.', 'error')
            return redirect(url_for('crypto.htg_wallet'))

        rate       = _get_rate(db)
        amount_usdt = round(amount_htg / rate, 6)
        now         = _now()

        new_htg  = round(bal_htg - amount_htg, 2)
        bal_usdt = float(profile.get('balance_usdt') or 0)
        new_usdt = round(bal_usdt + amount_usdt, 6)

        db.table('profiles').update({
            'balance_htg':  new_htg,
            'balance_usdt': new_usdt,
        }).eq('id', uid).execute()

        db.table('htg_transactions').insert({
            'user_id':     uid,
            'type':        'convert',
            'amount_htg':  -amount_htg,
            'amount_usdt': amount_usdt,
            'rate':        rate,
            'description': f'Converted {amount_htg} HTG → {amount_usdt} USDT @ {rate} HTG/USDT',
            'status':      'completed',
            'created_at':  now,
        }).execute()

        flash(f'Converted {amount_htg} HTG → {amount_usdt:.6f} USDT successfully!', 'success')

    except Exception as e:
        logger.error(f'[convert_htg_to_usdt] {e}')
        flash(f'Conversion error: {e}', 'error')

    return redirect(url_for('crypto.htg_wallet'))


# ── CONVERT USDT → HTG ───────────────────────────────────────────────────────

@crypto_bp.route('/convert-usdt-to-htg', methods=['POST'])
@login_required
def convert_usdt_to_htg():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount_usdt = float(request.form.get('amount_usdt', 0))
        if amount_usdt <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('crypto.htg_wallet'))

        profile  = _get_profile(db, uid)
        bal_usdt = float(profile.get('balance_usdt') or 0)

        if amount_usdt > bal_usdt:
            flash('Insufficient USDT balance.', 'error')
            return redirect(url_for('crypto.htg_wallet'))

        rate       = _get_rate(db)
        amount_htg = round(amount_usdt * rate, 2)
        now        = _now()

        new_usdt = round(bal_usdt - amount_usdt, 6)
        bal_htg  = float(profile.get('balance_htg') or 0)
        new_htg  = round(bal_htg + amount_htg, 2)

        db.table('profiles').update({
            'balance_htg':  new_htg,
            'balance_usdt': new_usdt,
        }).eq('id', uid).execute()

        db.table('htg_transactions').insert({
            'user_id':     uid,
            'type':        'convert',
            'amount_htg':  amount_htg,
            'amount_usdt': -amount_usdt,
            'rate':        rate,
            'description': f'Converted {amount_usdt} USDT → {amount_htg} HTG @ {rate} HTG/USDT',
            'status':      'completed',
            'created_at':  now,
        }).execute()

        flash(f'Converted {amount_usdt} USDT → {amount_htg} HTG successfully!', 'success')

    except Exception as e:
        logger.error(f'[convert_usdt_to_htg] {e}')
        flash(f'Conversion error: {e}', 'error')

    return redirect(url_for('crypto.htg_wallet'))


# ── HTG WITHDRAWAL (to NatCash) ───────────────────────────────────────────────

@crypto_bp.route('/htg-withdraw', methods=['POST'])
@login_required
def htg_withdraw():
    db  = get_admin_supabase()
    uid = session['user_id']

    try:
        amount_htg     = float(request.form.get('amount_htg', 0))
        natcash_number = request.form.get('natcash_number', '').strip()

        if amount_htg <= 0:
            flash('Amount must be greater than zero.', 'error')
            return redirect(url_for('crypto.htg_wallet'))

        if not natcash_number:
            flash('NatCash number is required.', 'error')
            return redirect(url_for('crypto.htg_wallet'))

        profile = _get_profile(db, uid)
        bal_htg = float(profile.get('balance_htg') or 0)

        if amount_htg > bal_htg:
            flash('Insufficient HTG balance.', 'error')
            return redirect(url_for('crypto.htg_wallet'))

        # Deduct immediately; admin confirms payment
        new_htg = round(bal_htg - amount_htg, 2)
        now     = _now()

        db.table('profiles').update({'balance_htg': new_htg}).eq('id', uid).execute()

        db.table('htg_withdrawals').insert({
            'user_id':        uid,
            'amount_htg':     amount_htg,
            'natcash_number': natcash_number,
            'status':         'pending',
            'created_at':     now,
        }).execute()

        db.table('htg_transactions').insert({
            'user_id':     uid,
            'type':        'withdrawal_htg',
            'amount_htg':  -amount_htg,
            'description': f'HTG withdrawal of {amount_htg} HTG to NatCash {natcash_number}',
            'status':      'pending',
            'created_at':  now,
        }).execute()

        flash(f'HTG withdrawal of {amount_htg} HTG submitted! Admin will send to your NatCash shortly.', 'success')

    except Exception as e:
        logger.error(f'[htg_withdraw] {e}')
        flash(f'Withdrawal error: {e}', 'error')

    return redirect(url_for('crypto.htg_wallet'))
