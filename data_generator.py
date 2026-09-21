import numpy as np, pandas as pd
DISTRICTS={
'Cầu Giấy':(21.0362,105.7906,80), 'Ba Đình':(21.0333,105.8142,70), 'Đống Đa':(21.0188,105.8298,75),
'Thanh Xuân':(20.9959,105.8062,70), 'Hai Bà Trưng':(20.9980,105.8525,60), 'Hoàng Mai':(20.9846,105.8580,45)}

def generate_orders(n=400,seed=42):
    rng=np.random.default_rng(seed); rows=[]
    names=list(DISTRICTS)
    probs=np.array([DISTRICTS[x][2] for x in names]); probs=probs/probs.sum()
    windows=['08:00-12:00','13:00-17:00','09:00-11:00']
    for i in range(1,n+1):
        d=rng.choice(names,p=probs); lat0,lon0,_=DISTRICTS[d]
        lat=lat0+rng.normal(0,0.012); lon=lon0+rng.normal(0,0.015)
        rows.append([f'DH{i:03d}',d,lat,lon,float(rng.uniform(1,8)),rng.choice(windows,p=[.55,.3,.15]),int(rng.integers(3,9))])
    return pd.DataFrame(rows,columns=['order_id','district','lat','lon','weight','time_window','service_min'])

def default_fleet():
    rows=[]
    for i in range(1,13): rows.append([f'MB-{i:02d}','Motorbike',50,2.26,850])
    for i in range(1,7): rows.append([f'TK5-{i:02d}','Small truck 500kg',500,10,2200])
    for i in range(1,3): rows.append([f'TK7-{i:02d}','Small truck 700kg',700,10,2500])
    return pd.DataFrame(rows,columns=['vehicle_id','vehicle_type','capacity','fuel_l_100km','cost_per_km'])
