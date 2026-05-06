from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import firebase_admin
from firebase_admin import credentials, db
import hashlib, os, uuid, requests
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'loska-secret-2024-change-in-production')

# ── Firebase ──────────────────────────────────────────────────────────────────
try:
    cred = credentials.Certificate('serviceAccountKey.json')
    firebase_admin.initialize_app(cred, {
        'databaseURL': os.environ.get('FIREBASE_DATABASE_URL', 'https://your-project-default-rtdb.firebaseio.com')
    })
    firebase_connected = True
except Exception as e:
    print(f"Firebase not connected: {e}")
    firebase_connected = False

# ── Helpers ───────────────────────────────────────────────────────────────────
def hash_password(p): return hashlib.sha256(p.encode()).hexdigest()
def get_db_ref(path): return db.reference(path) if firebase_connected else None
def get_cart(): return session.get('cart', {})
def save_cart(c): session['cart'] = c

def get_item_from_db(item_id):
    ref = get_db_ref(f'products/{item_id}')
    item = ref.get() if ref else None
    if item:
        item['item_type'] = 'product'
        item['display_name'] = f"{item.get('brand','')} {item.get('model','')}"
        return item
    ref = get_db_ref(f'accessories/{item_id}')
    item = ref.get() if ref else None
    if item:
        item['item_type'] = 'accessory'
        item['display_name'] = item.get('name', '')
        return item
    return None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ── M-Pesa ────────────────────────────────────────────────────────────────────
MPESA_CONSUMER_KEY    = os.environ.get('MPESA_CONSUMER_KEY', '')
MPESA_CONSUMER_SECRET = os.environ.get('MPESA_CONSUMER_SECRET', '')
MPESA_SHORTCODE       = os.environ.get('MPESA_SHORTCODE', '174379')
MPESA_PASSKEY         = os.environ.get('MPESA_PASSKEY', '')
MPESA_CALLBACK_URL    = os.environ.get('MPESA_CALLBACK_URL', 'https://yourdomain.com/mpesa/callback')
MPESA_BASE_URL        = 'https://sandbox.safaricom.co.ke'

def get_mpesa_token():
    try:
        r = requests.get(f'{MPESA_BASE_URL}/oauth/v1/generate?grant_type=client_credentials',
                         auth=(MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET), timeout=10)
        return r.json().get('access_token')
    except Exception as e:
        print(f"M-Pesa token error: {e}"); return None

def stk_push(phone, amount, account_ref, description):
    token = get_mpesa_token()
    if not token: return {'success': False, 'message': 'Could not connect to M-Pesa'}
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    import base64
    password = base64.b64encode(f"{MPESA_SHORTCODE}{MPESA_PASSKEY}{timestamp}".encode()).decode()
    phone = phone.strip().replace('+', '')
    if phone.startswith('0'): phone = '254' + phone[1:]
    payload = {"BusinessShortCode": MPESA_SHORTCODE, "Password": password, "Timestamp": timestamp,
               "TransactionType": "CustomerPayBillOnline", "Amount": int(amount),
               "PartyA": phone, "PartyB": MPESA_SHORTCODE, "PhoneNumber": phone,
               "CallBackURL": MPESA_CALLBACK_URL, "AccountReference": account_ref, "TransactionDesc": description}
    try:
        r = requests.post(f'{MPESA_BASE_URL}/mpesa/stkpush/v1/processrequest', json=payload,
                          headers={'Authorization': f'Bearer {token}'}, timeout=15)
        res = r.json()
        if res.get('ResponseCode') == '0':
            return {'success': True, 'checkout_id': res.get('CheckoutRequestID'), 'message': 'STK push sent!'}
        return {'success': False, 'message': res.get('CustomerMessage', 'Payment failed')}
    except Exception as e:
        return {'success': False, 'message': str(e)}

# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC PAGES
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def home():
    featured_phones, featured_accessories = [], []
    try:
        p_ref = get_db_ref('products')
        if p_ref:
            data = p_ref.get()
            if data:
                all_p = [{'id': k, **v} for k, v in data.items()]
                featured_phones = [p for p in all_p if p.get('featured')][:6]
    except Exception as e: print(f"Home phones error: {e}")
    try:
        a_ref = get_db_ref('accessories')
        if a_ref:
            data = a_ref.get()
            if data:
                all_a = [{'id': k, **v} for k, v in data.items()]
                featured_accessories = [a for a in all_a if a.get('featured')][:4]
    except Exception as e: print(f"Home accessories error: {e}")
    return render_template('home.html', featured=featured_phones, featured_accessories=featured_accessories)

# ── Info pages ────────────────────────────────────────────────────────────────
@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/services')
def services():
    return render_template('services.html')

@app.route('/our-team')
def our_team():
    return render_template('our_team.html')

@app.route('/partners')
def partners():
    return render_template('partners.html')

@app.route('/faqs')
def faqs():
    return render_template('faqs.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        # In production: send email via SendGrid / SMTP
        flash('Thank you! Your message has been sent. We\'ll respond within 24 hours.', 'success')
        return redirect(url_for('contact'))
    return render_template('contact.html')

# ── Products (Phones) ─────────────────────────────────────────────────────────
@app.route('/products')
def products():
    category = request.args.get('category', '')
    search   = request.args.get('search', '')
    ref = get_db_ref('products')
    all_products = []
    if ref:
        data = ref.get()
        if data: all_products = [{'id': k, **v} for k, v in data.items()]
    if category: all_products = [p for p in all_products if p.get('brand','').lower() == category.lower()]
    if search:   all_products = [p for p in all_products if search.lower() in p.get('brand','').lower() or search.lower() in p.get('model','').lower()]
    return render_template('products.html', products=all_products, category=category, search=search)

@app.route('/product/<product_id>')
def product_detail(product_id):
    ref = get_db_ref(f'products/{product_id}')
    product = ref.get() if ref else None
    if product: product['id'] = product_id
    return render_template('product_detail.html', product=product)

# ── Accessories ───────────────────────────────────────────────────────────────
@app.route('/accessories')
def accessories():
    category = request.args.get('category', '')
    search   = request.args.get('search', '')
    ref = get_db_ref('accessories')
    all_items = []
    if ref:
        data = ref.get()
        if data: all_items = [{'id': k, **v} for k, v in data.items()]
    if category: all_items = [a for a in all_items if a.get('category','').lower() == category.lower()]
    if search:   all_items = [a for a in all_items if search.lower() in a.get('name','').lower() or search.lower() in a.get('brand','').lower()]
    return render_template('accessories.html', accessories=all_items, category=category, search=search)

@app.route('/accessory/<item_id>')
def accessory_detail(item_id):
    ref = get_db_ref(f'accessories/{item_id}')
    item = ref.get() if ref else None
    if item: item['id'] = item_id
    return render_template('accessory_detail.html', item=item)

# ── Cart ──────────────────────────────────────────────────────────────────────
@app.route('/cart')
def cart():
    cart_data = get_cart()
    items, total = [], 0
    for iid, qty in cart_data.items():
        item = get_item_from_db(iid)
        if item:
            subtotal = item.get('price', 0) * qty
            total += subtotal
            items.append({'id': iid, 'qty': qty, 'subtotal': subtotal, **item})
    return render_template('cart.html', items=items, total=total)

@app.route('/cart/add/<item_id>', methods=['POST'])
def add_to_cart(item_id):
    cart_data = get_cart()
    qty = int(request.form.get('quantity', 1))
    cart_data[item_id] = cart_data.get(item_id, 0) + qty
    save_cart(cart_data)
    flash('Item added to cart!', 'success')
    return redirect(request.referrer or url_for('products'))

@app.route('/cart/update', methods=['POST'])
def update_cart():
    cart_data = get_cart()
    pid = request.form.get('product_id')
    qty = int(request.form.get('quantity', 1))
    if qty <= 0: cart_data.pop(pid, None)
    else: cart_data[pid] = qty
    save_cart(cart_data)
    return redirect(url_for('cart'))

@app.route('/cart/remove/<item_id>')
def remove_from_cart(item_id):
    cart_data = get_cart()
    cart_data.pop(item_id, None)
    save_cart(cart_data)
    flash('Item removed.', 'info')
    return redirect(url_for('cart'))

# ── Checkout ──────────────────────────────────────────────────────────────────
@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart_data = get_cart()
    if not cart_data:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('products'))
    items, total = [], 0
    for iid, qty in cart_data.items():
        item = get_item_from_db(iid)
        if item:
            subtotal = item.get('price', 0) * qty
            total += subtotal
            items.append({'id': iid, 'qty': qty, 'subtotal': subtotal, **item})
    if request.method == 'POST':
        order_id = str(uuid.uuid4())[:8].upper()
        order = {
            'order_id': order_id, 'user_id': session['user_id'],
            'user_name': request.form.get('name'), 'phone': request.form.get('phone'),
            'address': request.form.get('address'), 'products': cart_data,
            'total_amount': total, 'payment_method': request.form.get('payment_method'),
            'status': 'pending_payment', 'order_date': datetime.now().isoformat()
        }
        ref = get_db_ref('orders')
        if ref: ref.child(order_id).set(order)
        payment = request.form.get('payment_method')
        if payment == 'mpesa':   return redirect(url_for('pay_mpesa', order_id=order_id))
        elif payment == 'card':  return redirect(url_for('pay_card', order_id=order_id))
        else:
            save_cart({})
            flash(f'Order #{order_id} placed! Pay on delivery.', 'success')
            return redirect(url_for('order_confirmation', order_id=order_id))
    return render_template('checkout.html', items=items, total=total)

@app.route('/pay/mpesa/<order_id>', methods=['GET', 'POST'])
@login_required
def pay_mpesa(order_id):
    ref = get_db_ref(f'orders/{order_id}')
    order = ref.get() if ref else None
    if not order: flash('Order not found.', 'danger'); return redirect(url_for('home'))
    if request.method == 'POST':
        phone = request.form.get('phone', order.get('phone', ''))
        result = stk_push(phone, order['total_amount'], f'LOSKA-{order_id}', 'Loska Communications Order')
        if result['success']:
            if ref: ref.update({'status': 'payment_initiated', 'mpesa_checkout_id': result.get('checkout_id')})
            return render_template('pay_mpesa.html', order=order, order_id=order_id, message=result['message'], success=True)
        return render_template('pay_mpesa.html', order=order, order_id=order_id, message=result['message'], success=False)
    return render_template('pay_mpesa.html', order=order, order_id=order_id)

@app.route('/mpesa/callback', methods=['POST'])
def mpesa_callback():
    data = request.get_json()
    try:
        cb = data['Body']['stkCallback']
        checkout_id, result_code = cb['CheckoutRequestID'], cb['ResultCode']
        ref = get_db_ref('orders')
        if ref:
            orders = ref.get()
            if orders:
                for oid, o in orders.items():
                    if o.get('mpesa_checkout_id') == checkout_id:
                        ref.child(oid).update({'status': 'paid' if result_code == 0 else 'payment_failed'})
                        break
    except Exception as e: print(f"M-Pesa callback error: {e}")
    return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'})

@app.route('/pay/card/<order_id>', methods=['GET', 'POST'])
@login_required
def pay_card(order_id):
    ref = get_db_ref(f'orders/{order_id}')
    order = ref.get() if ref else None
    if request.method == 'POST':
        if ref: ref.update({'status': 'paid'})
        save_cart({})
        flash(f'Payment successful! Order #{order_id} confirmed.', 'success')
        return redirect(url_for('order_confirmation', order_id=order_id))
    return render_template('pay_card.html', order=order, order_id=order_id)

@app.route('/order/confirmation/<order_id>')
@login_required
def order_confirmation(order_id):
    ref = get_db_ref(f'orders/{order_id}')
    order = ref.get() if ref else None
    save_cart({})
    return render_template('order_confirmation.html', order=order, order_id=order_id)

# ── Airtime ───────────────────────────────────────────────────────────────────
@app.route('/airtime', methods=['GET', 'POST'])
def airtime():
    if request.method == 'POST':
        phone, network, amount, payment = (request.form.get(k) for k in ['phone','network','amount','payment_method'])
        txn_id = str(uuid.uuid4())[:8].upper()
        record = {'transaction_id': txn_id, 'user_id': session.get('user_id', 'guest'),
                  'phone_number': phone, 'network': network, 'amount': int(amount),
                  'payment_method': payment, 'status': 'pending', 'date': datetime.now().isoformat()}
        ref = get_db_ref('airtime')
        if ref: ref.child(txn_id).set(record)
        if payment == 'mpesa':
            result = stk_push(phone, amount, f'AIRTIME-{txn_id}', f'Airtime for {phone}')
            if result['success']:
                if ref: ref.child(txn_id).update({'status': 'initiated'})
                flash(f'M-Pesa prompt sent! Ref: {txn_id}', 'success')
            else: flash(f'Payment error: {result["message"]}', 'danger')
        else:
            if ref: ref.child(txn_id).update({'status': 'completed'})
            flash(f'Airtime purchase successful! Ref: {txn_id}', 'success')
        return redirect(url_for('airtime'))
    return render_template('airtime.html')

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name, email, password = request.form.get('name'), request.form.get('email'), request.form.get('password')
        ref = get_db_ref('users')
        if ref:
            existing = ref.order_by_child('email').equal_to(email).get()
            if existing: flash('Email already registered.', 'warning'); return redirect(url_for('register'))
        user_id = str(uuid.uuid4())
        user = {'user_id': user_id, 'name': name, 'email': email,
                'password': hash_password(password), 'role': 'customer', 'created_at': datetime.now().isoformat()}
        if ref: ref.child(user_id).set(user)
        session.update({'user_id': user_id, 'name': name, 'email': email, 'role': 'customer'})
        flash(f'Welcome to Loska, {name}!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email, password = request.form.get('email'), request.form.get('password')
        ref = get_db_ref('users')
        user_data = None
        if ref:
            data = ref.order_by_child('email').equal_to(email).get()
            if data: user_data = list(data.values())[0]
        if user_data and user_data.get('password') == hash_password(password):
            session.update({'user_id': user_data['user_id'], 'name': user_data['name'],
                            'email': user_data['email'], 'role': user_data.get('role','customer')})
            flash(f'Welcome back, {user_data["name"]}!', 'success')
            return redirect(url_for('admin_dashboard') if session['role'] == 'admin' else url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); flash('You have been logged out.', 'info'); return redirect(url_for('home'))

# ── User Dashboard ─────────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    uid = session['user_id']
    orders, airtime_txns = [], []
    try:
        o_ref = get_db_ref('orders')
        if o_ref:
            data = o_ref.order_by_child('user_id').equal_to(uid).get()
            if data: orders = [{'id': k, **v} for k, v in data.items()]
    except Exception: pass
    try:
        a_ref = get_db_ref('airtime')
        if a_ref:
            data = a_ref.order_by_child('user_id').equal_to(uid).get()
            if data: airtime_txns = [{'id': k, **v} for k, v in data.items()]
    except Exception: pass
    return render_template('dashboard.html', orders=orders, airtime_txns=airtime_txns)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    uid = session['user_id']
    ref = get_db_ref(f'users/{uid}')
    if request.method == 'POST':
        updates = {'name': request.form.get('name'), 'phone': request.form.get('phone')}
        if ref: ref.update(updates)
        session['name'] = updates['name']
        flash('Profile updated!', 'success')
    user = ref.get() if ref else {}
    return render_template('profile.html', user=user)

# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/admin')
@admin_required
def admin_dashboard():
    stats = {'products': 0, 'accessories': 0, 'orders': 0, 'airtime_sales': 0, 'customers': 0, 'revenue': 0}
    orders = []
    for key, path in [('products','products'), ('accessories','accessories')]:
        try:
            ref = get_db_ref(path)
            if ref:
                data = ref.get(); stats[key] = len(data) if data else 0
        except Exception: pass
    try:
        o_ref = get_db_ref('orders')
        if o_ref:
            data = o_ref.get()
            if data:
                stats['orders'] = len(data)
                orders = [{'id': k, **v} for k, v in data.items()]
                stats['revenue'] = sum(o.get('total_amount', 0) for o in orders)
    except Exception: pass
    try:
        a_ref = get_db_ref('airtime')
        if a_ref:
            data = a_ref.get()
            if data: stats['airtime_sales'] = sum(v.get('amount', 0) for v in data.values())
    except Exception: pass
    return render_template('admin/dashboard.html', stats=stats, orders=orders)

# ── Admin: Phones ─────────────────────────────────────────────────────────────
@app.route('/admin/products')
@admin_required
def admin_products():
    ref = get_db_ref('products')
    products = []
    if ref:
        data = ref.get()
        if data: products = [{'id': k, **v} for k, v in data.items()]
    return render_template('admin/products.html', products=products)

@app.route('/admin/products/add', methods=['GET', 'POST'])
@admin_required
def admin_add_product():
    if request.method == 'POST':
        pid = str(uuid.uuid4())
        product = {'brand': request.form.get('brand'), 'model': request.form.get('model'),
                   'price': float(request.form.get('price', 0)), 'stock': int(request.form.get('stock', 0)),
                   'image_url': request.form.get('image_url', ''), 'description': request.form.get('description', ''),
                   'featured': request.form.get('featured') == 'on', 'created_at': datetime.now().isoformat()}
        ref = get_db_ref('products')
        if ref: ref.child(pid).set(product)
        flash('Phone added successfully!', 'success')
        return redirect(url_for('admin_products'))
    return render_template('admin/product_form.html', product=None, action='Add')

@app.route('/admin/products/edit/<product_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_product(product_id):
    ref = get_db_ref(f'products/{product_id}')
    if request.method == 'POST':
        updates = {'brand': request.form.get('brand'), 'model': request.form.get('model'),
                   'price': float(request.form.get('price', 0)), 'stock': int(request.form.get('stock', 0)),
                   'image_url': request.form.get('image_url', ''), 'description': request.form.get('description', ''),
                   'featured': request.form.get('featured') == 'on'}
        if ref: ref.update(updates)
        flash('Phone updated!', 'success')
        return redirect(url_for('admin_products'))
    product = ref.get() if ref else {}
    product['id'] = product_id
    return render_template('admin/product_form.html', product=product, action='Edit')

@app.route('/admin/products/delete/<product_id>', methods=['POST'])
@admin_required
def admin_delete_product(product_id):
    ref = get_db_ref(f'products/{product_id}')
    if ref: ref.delete()
    flash('Phone deleted.', 'info')
    return redirect(url_for('admin_products'))

# ── Admin: Accessories ────────────────────────────────────────────────────────
@app.route('/admin/accessories')
@admin_required
def admin_accessories():
    ref = get_db_ref('accessories')
    items = []
    if ref:
        data = ref.get()
        if data: items = [{'id': k, **v} for k, v in data.items()]
    return render_template('admin/accessories.html', accessories=items)

@app.route('/admin/accessories/add', methods=['GET', 'POST'])
@admin_required
def admin_add_accessory():
    if request.method == 'POST':
        aid = str(uuid.uuid4())
        accessory = {'name': request.form.get('name'), 'brand': request.form.get('brand', ''),
                     'category': request.form.get('category'),
                     'price': float(request.form.get('price', 0)), 'stock': int(request.form.get('stock', 0)),
                     'image_url': request.form.get('image_url', ''), 'description': request.form.get('description', ''),
                     'compatible': request.form.get('compatible', ''),
                     'featured': request.form.get('featured') == 'on', 'created_at': datetime.now().isoformat()}
        ref = get_db_ref('accessories')
        if ref: ref.child(aid).set(accessory)
        flash('Accessory added successfully!', 'success')
        return redirect(url_for('admin_accessories'))
    return render_template('admin/accessory_form.html', item=None, action='Add')

@app.route('/admin/accessories/edit/<item_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_accessory(item_id):
    ref = get_db_ref(f'accessories/{item_id}')
    if request.method == 'POST':
        updates = {'name': request.form.get('name'), 'brand': request.form.get('brand', ''),
                   'category': request.form.get('category'),
                   'price': float(request.form.get('price', 0)), 'stock': int(request.form.get('stock', 0)),
                   'image_url': request.form.get('image_url', ''), 'description': request.form.get('description', ''),
                   'compatible': request.form.get('compatible', ''),
                   'featured': request.form.get('featured') == 'on'}
        if ref: ref.update(updates)
        flash('Accessory updated!', 'success')
        return redirect(url_for('admin_accessories'))
    item = ref.get() if ref else {}
    item['id'] = item_id
    return render_template('admin/accessory_form.html', item=item, action='Edit')

@app.route('/admin/accessories/delete/<item_id>', methods=['POST'])
@admin_required
def admin_delete_accessory(item_id):
    ref = get_db_ref(f'accessories/{item_id}')
    if ref: ref.delete()
    flash('Accessory deleted.', 'info')
    return redirect(url_for('admin_accessories'))

# ── Admin: Orders & Airtime ───────────────────────────────────────────────────
@app.route('/admin/orders')
@admin_required
def admin_orders():
    ref = get_db_ref('orders')
    orders = []
    if ref:
        data = ref.get()
        if data: orders = [{'id': k, **v} for k, v in data.items()]
    return render_template('admin/orders.html', orders=orders)

@app.route('/admin/orders/update/<order_id>', methods=['POST'])
@admin_required
def update_order_status(order_id):
    status = request.form.get('status')
    ref = get_db_ref(f'orders/{order_id}')
    if ref: ref.update({'status': status})
    flash(f'Order {order_id} updated to {status}.', 'success')
    return redirect(url_for('admin_orders'))

@app.route('/admin/airtime')
@admin_required
def admin_airtime():
    ref = get_db_ref('airtime')
    txns = []
    if ref:
        data = ref.get()
        if data: txns = [{'id': k, **v} for k, v in data.items()]
    return render_template('admin/airtime.html', txns=txns)

# ── API ───────────────────────────────────────────────────────────────────────
@app.route('/api/cart-count')
def cart_count():
    return jsonify({'count': sum(get_cart().values())})

# ── Seed Demo Data ─────────────────────────────────────────────────────────────
@app.route('/seed-demo', methods=['POST'])
def seed_demo():
    p_ref = get_db_ref('products')
    a_ref = get_db_ref('accessories')
    u_ref = get_db_ref('users')
    if not p_ref:
        return jsonify({'error': 'Firebase not connected'})

    demo_phones = [
        {'brand':'Samsung','model':'Galaxy S24 Ultra','price':189999,'stock':10,'image_url':'https://images.unsplash.com/photo-1610945415295-d9bbf067e59c?w=400','description':'6.8" Display, 200MP Camera, 5000mAh','featured':True},
        {'brand':'iPhone','model':'iPhone 15 Pro Max','price':224999,'stock':8,'image_url':'https://images.unsplash.com/photo-1695048133142-1a20484d2569?w=400','description':'6.7" Super Retina, A17 Pro chip','featured':True},
        {'brand':'Tecno','model':'Spark 20 Pro','price':24999,'stock':25,'image_url':'https://images.unsplash.com/photo-1598327105666-5b89351aff97?w=400','description':'6.6" FHD+, 64MP Camera, 5000mAh','featured':True},
        {'brand':'Infinix','model':'Hot 40 Pro','price':19999,'stock':30,'image_url':'https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=400','description':'6.78" HD+, 50MP, 5000mAh','featured':True},
        {'brand':'Xiaomi','model':'Redmi Note 13 Pro','price':39999,'stock':15,'image_url':'https://images.unsplash.com/photo-1569429593410-b498b3fb3387?w=400','description':'6.67" AMOLED, 200MP, 5100mAh','featured':False},
        {'brand':'Samsung','model':'Galaxy A55','price':59999,'stock':12,'image_url':'https://images.unsplash.com/photo-1580910051074-3eb694886505?w=400','description':'6.6" Super AMOLED, 50MP, 5000mAh','featured':False},
    ]
    demo_accessories = [
        {'name':'AirPods Pro 2nd Gen','brand':'Apple','category':'Earphones','price':24999,'stock':20,'image_url':'https://images.unsplash.com/photo-1603351154351-5e2d0600bb77?w=400','description':'Active Noise Cancellation, H2 chip, 30hr battery','compatible':'iPhone, iPad, Mac','featured':True},
        {'name':'Samsung Galaxy Buds2 Pro','brand':'Samsung','category':'Earphones','price':18999,'stock':15,'image_url':'https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=400','description':'360 Audio, ANC, IPX7 water resistant','compatible':'Samsung, Android','featured':True},
        {'name':'Anker 65W GaN Charger','brand':'Anker','category':'Chargers','price':3499,'stock':50,'image_url':'https://images.unsplash.com/photo-1583863788434-e58a36330cf0?w=400','description':'65W USB-C fast charging, foldable plug','compatible':'Universal USB-C','featured':True},
        {'name':'Baseus 20000mAh Power Bank','brand':'Baseus','category':'Power Banks','price':5999,'stock':35,'image_url':'https://images.unsplash.com/photo-1609091839311-d5365f9ff1c5?w=400','description':'20000mAh, 65W fast charge, LED display','compatible':'All devices','featured':True},
        {'name':'Spigen Tough Armor Case','brand':'Spigen','category':'Cases','price':1999,'stock':60,'image_url':'https://images.unsplash.com/photo-1601784551446-20c9e07cdbdb?w=400','description':'Military-grade protection, dual layer','compatible':'Samsung Galaxy S24','featured':False},
        {'name':'9H Tempered Glass Protector','brand':'Loska','category':'Screen Protectors','price':499,'stock':100,'image_url':'https://images.unsplash.com/photo-1556656793-08538906a9f8?w=400','description':'9H hardness, full coverage, anti-fingerprint','compatible':'Universal','featured':False},
        {'name':'Remax 2m Braided USB-C Cable','brand':'Remax','category':'Cables','price':699,'stock':80,'image_url':'https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400','description':'100W fast charge support, 2 metres','compatible':'All USB-C devices','featured':False},
        {'name':'Xiaomi Mi Band 8','brand':'Xiaomi','category':'Wearables','price':4999,'stock':25,'image_url':'https://images.unsplash.com/photo-1575311373937-040b8e1fd5b6?w=400','description':'1.62" AMOLED, heart rate, SpO2, 16-day battery','compatible':'Android & iOS','featured':False},
    ]

    for p in demo_phones:
        p['created_at'] = datetime.now().isoformat()
        p_ref.child(str(uuid.uuid4())).set(p)
    for a in demo_accessories:
        a['created_at'] = datetime.now().isoformat()
        a_ref.child(str(uuid.uuid4())).set(a)

    admin_id = str(uuid.uuid4())
    u_ref.child(admin_id).set({
        'user_id': admin_id, 'name': 'Admin', 'email': 'admin@loska.co.ke',
        'password': hash_password('Admin@1234'), 'role': 'admin',
        'created_at': datetime.now().isoformat()
    })
    return jsonify({'success': True, 'message': 'Seeded 6 phones + 8 accessories + admin! Login: admin@loska.co.ke / Admin@1234'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
