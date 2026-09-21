import io
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import folium
from streamlit_folium import st_folium
from data_generator import generate_orders, default_fleet
from optimizer import baseline_routes, optimize_routes, ORTOOLS_AVAILABLE

st.set_page_config(page_title='EcoRoute Hanoi AI', page_icon='🚚', layout='wide', initial_sidebar_state='expanded')

CSS='''
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{--navy:#071a33;--ink:#0f172a;--muted:#64748b;--line:#e5eaf1;--green:#0f9d78;--soft:#f5f8fb}
html,body,[class*="css"]{font-family:Inter,sans-serif}.stApp{background:#f5f8fb}.block-container{max-width:1550px;padding:1.1rem 2rem 3rem}
[data-testid="stSidebar"]{background:#071a33}.hero{background:linear-gradient(135deg,#071a33,#0d3552 58%,#0f9d78);border-radius:22px;padding:28px 30px;color:white;box-shadow:0 16px 40px rgba(7,26,51,.16);margin-bottom:20px}.hero h1{margin:4px 0 6px;font-size:34px;font-weight:800}.hero p{margin:0;color:#d8e7f0}.eyebrow{display:inline-block;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.2);padding:5px 10px;border-radius:999px;font-size:11px;font-weight:800;letter-spacing:.08em}
.card{background:white;border:1px solid var(--line);border-radius:17px;padding:18px 20px;box-shadow:0 5px 20px rgba(15,23,42,.045)}.section-title{font-size:19px;font-weight:800;color:var(--ink);margin:18px 0 10px}.muted{color:var(--muted);font-size:12px}.big{font-size:27px;font-weight:800;color:var(--ink)}.green{color:var(--green);font-weight:700}.stButton>button{border-radius:11px;font-weight:700}.stDownloadButton>button{border-radius:11px;font-weight:700}.stTabs [data-baseweb="tab"]{font-weight:700}.status{padding:8px 11px;border-radius:10px;background:#ecfdf5;color:#047857;font-size:12px;font-weight:700}.warn{padding:10px 12px;border-radius:10px;background:#fff7ed;color:#c2410c;font-size:12px}
</style>'''
st.markdown(CSS, unsafe_allow_html=True)

# ---------- helpers ----------
DEPOT=(21.0285,105.8542)

def fmt_money(x): return f"₫{x:,.0f}"
def fmt_num(x): return f"{x:,.1f}"
def pct_change(base, new): return (base-new)/base*100 if base else 0

def metrics(df):
    if df is None or df.empty: return {'distance':0,'cost':0,'fuel':0,'co2':0,'vehicles':0,'orders':0}
    return {'distance':df.distance_km.sum(),'cost':df.cost_vnd.sum(),'fuel':df.fuel_l.sum(),'co2':df.co2_kg.sum(),'vehicles':len(df),'orders':int(df.orders.sum())}

def build_map(orders, routes=None, selected=None, show_orders=True):
    m=folium.Map(location=[21.025,105.835],zoom_start=12,tiles='CartoDB positron',control_scale=True)
    folium.Marker(DEPOT,tooltip='Depot — Hanoi',popup='Central Depot',icon=folium.Icon(color='black',icon='home')).add_to(m)
    if show_orders:
        for _,r in orders.iterrows():
            folium.CircleMarker([r.lat,r.lon],radius=3,weight=1,color='#0f9d78',fill=True,fill_opacity=.55,tooltip=f"{r.order_id} • {r.district}").add_to(m)
    if routes is not None and not routes.empty:
        palette=['#0f9d78','#2563eb','#7c3aed','#ea580c','#0891b2','#db2777','#65a30d','#475569']
        rows=routes if selected is None else routes[routes.vehicle_id==selected]
        for i,(_,r) in enumerate(rows.iterrows()):
            sub=orders[orders.order_id.isin(r.stops)].copy(); ordermap={x:j+1 for j,x in enumerate(r.stops)}; sub['stop']=sub.order_id.map(ordermap); sub=sub.sort_values('stop')
            pts=[list(DEPOT)]+sub[['lat','lon']].values.tolist()+[list(DEPOT)]
            folium.PolyLine(pts,color=palette[i%len(palette)],weight=5,opacity=.8,tooltip=f"{r.vehicle_id} • {r.distance_km:.1f} km").add_to(m)
            for _,x in sub.iterrows():
                folium.Marker([x.lat,x.lon],tooltip=f"Stop {int(x.stop)} • {x.order_id}",popup=f"{x.district} • {x.weight:.1f} kg • {x.time_window}",icon=folium.DivIcon(html=f'<div style="background:white;border:2px solid #0f9d78;border-radius:50%;width:24px;height:24px;text-align:center;font-size:11px;font-weight:800;line-height:20px">{int(x.stop)}</div>')).add_to(m)
    return m

# ---------- state ----------
if 'orders' not in st.session_state: st.session_state.orders=generate_orders(400,42)
if 'fleet' not in st.session_state: st.session_state.fleet=default_fleet()
if 'optimized' not in st.session_state: st.session_state.optimized=None
if 'baseline' not in st.session_state: st.session_state.baseline=None
if 'alpha' not in st.session_state: st.session_state.alpha=.60
if 'scenario' not in st.session_state: st.session_state.scenario='Normal'

# ---------- sidebar ----------
with st.sidebar:
    st.markdown('<div style="font-size:24px;font-weight:800;color:white">🚚 EcoRoute AI</div><div style="color:#9fb4c9;font-size:12px">HANOI • LAST-MILE CONTROL TOWER</div>',unsafe_allow_html=True)
    st.divider()
    page=st.radio('Navigation',['Dashboard','Orders','Fleet','AI Optimization','Routes','Analytics','Scenario Lab','Research'],label_visibility='collapsed')
    st.divider()
    st.markdown('**SYSTEM**')
    st.markdown(f'<div class="status">● {"OR-Tools ready" if ORTOOLS_AVAILABLE else "Heuristic fallback"}</div>',unsafe_allow_html=True)
    st.caption('EcoRoute Hanoi AI • V2 Research Prototype')
    st.caption('For real deployment: replace geographic proxy with road/traffic data.')

st.markdown('<div class="hero"><span class="eyebrow">AI-POWERED URBAN LOGISTICS</span><h1>EcoRoute Hanoi AI</h1><p>Intelligent last-mile routing to balance delivery cost, fleet utilization and CO₂ emissions.</p></div>',unsafe_allow_html=True)

# ---------- dashboard ----------
if page=='Dashboard':
    o=st.session_state.orders; r=st.session_state.optimized; b=st.session_state.baseline
    mm=metrics(r)
    cols=st.columns(6)
    cards=[('ORDERS',f"{len(o):,}",'Today'),('VEHICLES',f"{mm['vehicles']:,}",'Used after optimization' if r is not None else 'Not optimized'),('DISTANCE',f"{mm['distance']:,.0f} km",'Optimized route'),('COST',fmt_money(mm['cost']),'Estimated'),('FUEL',f"{mm['fuel']:,.1f} L",'Estimated'),('CO₂',f"{mm['co2']:,.1f} kg",'Estimated')]
    for c,(lab,val,sub) in zip(cols,cards): c.markdown(f'<div class="card"><div class="muted">{lab}</div><div class="big">{val}</div><div class="muted">{sub}</div></div>',unsafe_allow_html=True)
    st.markdown('<div class="section-title">Hanoi delivery network</div>',unsafe_allow_html=True)
    a,bcol=st.columns([1.65,1])
    with a:
        st_folium(build_map(o,r),height=545,use_container_width=True)
    with bcol:
        if r is not None and b is not None and not r.empty:
            bm,rm=metrics(b),metrics(r)
            st.markdown('<div class="card"><b>BEFORE → AFTER</b><br><span class="muted">Baseline heuristic vs optimized routing</span></div>',unsafe_allow_html=True)
            for label,key in [('Distance','distance'),('Cost','cost'),('Fuel','fuel'),('CO₂','co2')]:
                reduction=pct_change(bm[key],rm[key]); val=rm[key]
                display=fmt_money(val) if key=='cost' else f'{val:,.1f}'
                st.metric(label,display,f'{reduction:+.1f}%')
        else:
            st.info('Run AI Optimization to populate the control tower.')
    st.markdown('<div class="section-title">District demand</div>',unsafe_allow_html=True)
    dc=o.groupby('district').agg(Orders=('order_id','count'),Weight_kg=('weight','sum')).reset_index().sort_values('Orders',ascending=False)
    fig=px.bar(dc,x='district',y='Orders',text='Orders',template='plotly_white'); fig.update_layout(height=300,margin=dict(l=0,r=0,t=10,b=0),xaxis_title='',yaxis_title='Orders'); st.plotly_chart(fig,use_container_width=True)

# ---------- orders ----------
elif page=='Orders':
    st.markdown('<div class="section-title">Order management</div>',unsafe_allow_html=True)
    o=st.session_state.orders
    c1,c2,c3=st.columns([1,1.2,1])
    n=c1.selectbox('Demo size',[100,200,300,400,500],index=[100,200,300,400,500].index(len(o)) if len(o) in [100,200,300,400,500] else 3)
    if c1.button('Generate demo orders',use_container_width=True): st.session_state.orders=generate_orders(n,42+n); st.session_state.optimized=None; st.session_state.baseline=None; st.rerun()
    up=c2.file_uploader('Upload CSV / Excel',type=['csv','xlsx'])
    if up:
        df=pd.read_csv(up) if up.name.lower().endswith('.csv') else pd.read_excel(up)
        required=['order_id','district','lat','lon','weight','time_window','service_min']
        missing=[x for x in required if x not in df.columns]
        if not missing:
            st.session_state.orders=df[required].copy(); st.session_state.optimized=None; st.session_state.baseline=None; st.success(f'Loaded {len(df):,} orders from {up.name}.'); st.rerun()
        else: st.error('Missing columns: '+', '.join(missing))
    sample=st.session_state.orders.copy();
    st.dataframe(sample,use_container_width=True,height=480)
    xlsx=io.BytesIO(); sample.to_excel(xlsx,index=False,engine='openpyxl'); xlsx.seek(0)
    d1,d2=st.columns(2); d1.download_button('⬇ Download current CSV',sample.to_csv(index=False),'ecoroute_orders.csv','text/csv',use_container_width=True); d2.download_button('⬇ Download current Excel',xlsx,'ecoroute_orders.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
    st.caption('Required schema: order_id, district, lat, lon, weight, time_window, service_min.')

# ---------- fleet ----------
elif page=='Fleet':
    st.markdown('<div class="section-title">Fleet configuration</div>',unsafe_allow_html=True)
    f=st.session_state.fleet.copy()
    edited=st.data_editor(f,use_container_width=True,num_rows='dynamic',hide_index=True,column_config={'capacity':st.column_config.NumberColumn('Capacity (kg)',min_value=1),'fuel_l_100km':st.column_config.NumberColumn('Fuel (L/100km)',min_value=.01),'cost_per_km':st.column_config.NumberColumn('Cost/km (VND)',min_value=0)},key='fleet_editor')
    st.session_state.fleet=edited
    st.markdown('<div class="card"><b>Default research fleet</b><br><span class="muted">12 motorbikes × 50 kg • 6 trucks × 500 kg • 2 trucks × 700 kg</span></div>',unsafe_allow_html=True)

# ---------- optimization ----------
elif page=='AI Optimization':
    st.markdown('<div class="section-title">AI Optimization Control Center</div>',unsafe_allow_html=True)
    a,bcol=st.columns([1,1])
    with a:
        alpha=st.slider('Cost priority (α)',0.0,1.0,st.session_state.alpha,.05); st.session_state.alpha=alpha
        scenario=st.selectbox('Traffic scenario',['Normal','Peak'],index=0 if st.session_state.scenario=='Normal' else 1); st.session_state.scenario=scenario
        limit=st.slider('Optimization time limit (seconds)',3,30,10)
    with bcol:
        st.markdown('<div class="card"><b>Objective function</b><br><span style="font-size:22px;font-weight:800">α × Cost + (1 − α) × CO₂</span><br><span class="muted">Normalized multi-objective decision support</span><hr><span class="status">✓ Capacity</span> <span class="status">✓ Time windows</span> <span class="status">✓ 600-min workday</span></div>',unsafe_allow_html=True)
    st.progress(alpha,text=f'Cost {alpha:.0%}  •  Environment {(1-alpha):.0%}')
    if st.button('🚀 RUN AI OPTIMIZATION',type='primary',use_container_width=True):
        with st.spinner(f'Optimizing {len(st.session_state.orders):,} orders under {scenario.lower()} traffic...'):
            base,_=baseline_routes(st.session_state.orders,st.session_state.fleet,peak=(scenario=='Peak'))
            res,engine=optimize_routes(st.session_state.orders,st.session_state.fleet,alpha=alpha,peak=(scenario=='Peak'),time_limit=limit)
        st.session_state.baseline=base; st.session_state.optimized=res; st.session_state.engine=engine
        st.success(f'Optimization complete • engine: {engine}')
        st.rerun()
    if st.session_state.optimized is not None:
        r=st.session_state.optimized;b=st.session_state.baseline; rm,bm=metrics(r),metrics(b)
        cols=st.columns(4)
        for c,label,key in zip(cols,['Distance','Cost','Fuel','CO₂'],['distance','cost','fuel','co2']): c.metric(label,fmt_money(rm[key]) if key=='cost' else f'{rm[key]:,.1f}',f'{pct_change(bm[key],rm[key]):+.1f}% vs baseline')
        st.markdown('<div class="section-title">Route summary</div>',unsafe_allow_html=True); st.dataframe(r.drop(columns=['stops']),use_container_width=True,height=300)

# ---------- routes ----------
elif page=='Routes':
    st.markdown('<div class="section-title">Routes & live-style dispatch view</div>',unsafe_allow_html=True)
    if st.session_state.optimized is None: st.info('Run AI Optimization first.'); st.stop()
    r=st.session_state.optimized;o=st.session_state.orders
    selected=st.selectbox('Vehicle route',r.vehicle_id.tolist())
    row=r[r.vehicle_id==selected].iloc[0]
    sub=o[o.order_id.isin(row.stops)].copy(); ordermap={x:i+1 for i,x in enumerate(row.stops)}; sub['stop']=sub.order_id.map(ordermap); sub=sub.sort_values('stop')
    cols=st.columns(6)
    for c,label,val in zip(cols,['Stops','Distance','Duration','Load','Cost','CO₂'],[row.orders,f'{row.distance_km:.1f} km',f'{row.duration_min:.0f} min',f'{row.load_kg:.1f}/{row.capacity_kg:.0f} kg',fmt_money(row.cost_vnd),f'{row.co2_kg:.2f} kg']): c.metric(label,val)
    left,right=st.columns([1.7,1])
    with left: st_folium(build_map(o,r,selected=selected,show_orders=False),height=590,use_container_width=True)
    with right:
        st.markdown('<div class="card"><b>STOP SEQUENCE</b><br><span class="muted">Recommended delivery order</span></div>',unsafe_allow_html=True)
        st.dataframe(sub[['stop','order_id','district','weight','time_window','service_min']],use_container_width=True,height=500)

# ---------- analytics ----------
elif page=='Analytics':
    st.markdown('<div class="section-title">Performance analytics</div>',unsafe_allow_html=True)
    if st.session_state.optimized is None: st.info('Run AI Optimization first.'); st.stop()
    r=st.session_state.optimized;b=st.session_state.baseline;rm,bm=metrics(r),metrics(b)
    c1,c2=st.columns(2)
    with c1:
        fig=px.bar(r,x='vehicle_id',y='utilization_pct',text_auto='.0f',template='plotly_white',title='Fleet utilization (%)'); fig.update_layout(height=360); st.plotly_chart(fig,use_container_width=True)
    with c2:
        fig=px.scatter(r,x='distance_km',y='co2_kg',size='orders',hover_name='vehicle_id',template='plotly_white',title='Distance vs CO₂ by vehicle'); fig.update_layout(height=360); st.plotly_chart(fig,use_container_width=True)
    comp=pd.DataFrame({'Metric':['Distance (km)','Cost (VND)','Fuel (L)','CO₂ (kg)'],'Baseline':[bm['distance'],bm['cost'],bm['fuel'],bm['co2']],'Optimized':[rm['distance'],rm['cost'],rm['fuel'],rm['co2']]})
    fig=px.bar(comp,x='Metric',y=['Baseline','Optimized'],barmode='group',template='plotly_white',title='Baseline vs optimized'); fig.update_layout(height=380); st.plotly_chart(fig,use_container_width=True)
    st.dataframe(r.drop(columns=['stops']),use_container_width=True)

# ---------- scenario ----------
elif page=='Scenario Lab':
    st.markdown('<div class="section-title">Scenario Lab</div>',unsafe_allow_html=True)
    st.caption('Thử nghiệm quy mô đơn hàng, giao thông và mức ưu tiên chi phí/CO₂. Kết quả dùng cùng engine tối ưu của app.')
    c1,c2,c3=st.columns(3); n=c1.selectbox('Orders',[100,200,300,400,500],index=3); traffic=c2.selectbox('Traffic',['Normal','Peak']); alpha=c3.slider('Cost priority α',0.,1.,.60,.05)
    if st.button('🧪 RUN SCENARIO',type='primary',use_container_width=True):
        demo=generate_orders(n,100+n); peak=traffic=='Peak'
        base,_=baseline_routes(demo,st.session_state.fleet,peak=peak); res,engine=optimize_routes(demo,st.session_state.fleet,alpha=alpha,peak=peak,time_limit=10)
        st.session_state.scenario_result=(demo,base,res,engine,n,traffic,alpha)
    if 'scenario_result' in st.session_state:
        demo,base,res,engine,n,traffic,alpha=st.session_state.scenario_result; bm,rm=metrics(base),metrics(res)
        st.success(f'{n} orders • {traffic} traffic • α={alpha:.2f} • {engine}')
        rows=[]
        for label,key in [('Distance','distance'),('Cost','cost'),('Fuel','fuel'),('CO₂','co2')]: rows.append([label,bm[key],rm[key],pct_change(bm[key],rm[key])])
        st.dataframe(pd.DataFrame(rows,columns=['Metric','Baseline','Optimized','Reduction %']),use_container_width=True,hide_index=True)
        fig=px.bar(pd.DataFrame(rows,columns=['Metric','Baseline','Optimized','Reduction %']),x='Metric',y=['Baseline','Optimized'],barmode='group',template='plotly_white'); st.plotly_chart(fig,use_container_width=True)

# ---------- research ----------
elif page=='Research':
    st.markdown('<div class="section-title">Research transparency</div>',unsafe_allow_html=True)
    st.markdown('### Model implemented')
    st.latex(r'\min Z = \alpha Z_1 + (1-\alpha)Z_2')
    c1,c2=st.columns(2)
    with c1:
        st.markdown('<div class="card"><b>Z₁ — Delivery cost</b><br><span class="muted">Sum of distance × vehicle-specific cost/km.</span><br><br><b>Z₂ — CO₂</b><br><span class="muted">Fuel consumption × emission factor.</span></div>',unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="card"><b>Constraints</b><br><span class="muted">Vehicle capacity • time windows • service time • maximum work time • each order served once • depot start/end.</span></div>',unsafe_allow_html=True)
    st.markdown('### Prototype → production gap')
    st.warning('V2 vẫn dùng khoảng cách địa lý × hệ số 1.18 làm proxy. Muốn áp dụng thực tế cần road-distance/time matrix, traffic data, geocoding, validation dữ liệu và quy trình vận hành.')
    st.info('Về học thuật, nên gọi lõi này là AI-assisted / intelligent optimization: VRPTW + OR-Tools. Không nên mô tả OR-Tools tự thân là machine-learning model.')
    st.markdown('### Suggested production architecture')
    st.code('Frontend: Next.js / React\nBackend: FastAPI + Python\nOptimization: OR-Tools\nDatabase: PostgreSQL\nRouting: road-network API / OSRM / Map service\nDeployment: cloud hosting',language='text')
