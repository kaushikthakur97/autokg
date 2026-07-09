import polars as pl
from pathlib import Path
Path('silver').mkdir(exist_ok=True)
pl.DataFrame({'customer_id':['C001','C002'],'name':['Ada Lovelace','Grace Hopper'],'email':['ada@example.com','grace@example.com'],'segment':['VIP','Standard']}).write_csv('silver/customers.csv')
pl.DataFrame({'policy_id':['P100','P200'],'customer_id':['C001','C002'],'policy_type':['Auto','Home'],'status':['Active','Active']}).write_csv('silver/policies.csv')
pl.DataFrame({'claim_id':['CL900','CL901'],'policy_id':['P100','P200'],'claim_amount':[12500,3200],'status':['Open','Closed']}).write_csv('silver/claims.csv')
print('Demo insurance CSVs written to silver/')
