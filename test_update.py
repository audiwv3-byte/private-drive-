import ast
from pathlib import Path
p=Path(__file__).with_name('Euro_Baltic_Transfer.py')
s=p.read_text()
t=ast.parse(s)
functions={x.name for x in t.body if isinstance(x,ast.FunctionDef)}
for name in ('payment_button','payment_menu','crypto_menu','admin_crypto_amount','admin_card_link','claim_payment','admin_verify_payment','status_change','duration_display'):
    assert name in functions,name
assert '🚘 Автомобиль и пилот' in s
assert "pilot_card.jpg" in s
assert '✅ Нет пожеланий' in s
assert "USDC', 'BTC', 'ETH" in s
assert "f\"Пассажиры" not in s and 'До 4 пассажиров' not in s
assert '🧳 {st[' not in s
assert 'Платёж: ' in s
assert 'Заказ №' in s
print('PASS: payment workflow, photo, simplified booking, duration, admin controls')
