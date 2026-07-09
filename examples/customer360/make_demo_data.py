import polars as pl
from pathlib import Path
Path('silver').mkdir(exist_ok=True)
pl.DataFrame({'customer_id':['C001','C002'],'name':['Ada Lovelace','Grace Hopper'],'email':['ada@example.com','grace@example.com'],'segment':['VIP','Standard']}).write_csv('silver/customers.csv')
pl.DataFrame({'product_id':['PR1','PR2'],'name':['Risk Scanner','Analytics Seat'],'risk_level':['High','Low']}).write_csv('silver/products.csv')
pl.DataFrame({'order_id':['O100','O101'],'customer_id':['C001','C002'],'product_id':['PR1','PR2'],'amount':[4999,299]}).write_csv('silver/orders.csv')
print('Demo customer360 CSVs written to silver/')
