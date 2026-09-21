import math, random
import pandas as pd
import numpy as np

try:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    ORTOOLS_AVAILABLE = True
except Exception:
    ORTOOLS_AVAILABLE = False

FUEL = {"Motorbike": 0.0226, "Small truck 500kg": 0.10, "Small truck 700kg": 0.10}
CAP = {"Motorbike": 50, "Small truck 500kg": 500, "Small truck 700kg": 700}
COST_PER_KM = {"Motorbike": 850, "Small truck 500kg": 2200, "Small truck 700kg": 2500}
EMISSION_FACTOR = 2.31


def haversine_km(lat1, lon1, lat2, lon2):
    R=6371.0
    p1,p2=math.radians(lat1),math.radians(lat2)
    dlat=math.radians(lat2-lat1); dlon=math.radians(lon2-lon1)
    a=math.sin(dlat/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(a))


def travel_minutes(distance_km, vehicle_type, peak=False):
    speed = 20 if vehicle_type == 'Motorbike' and peak else 30 if vehicle_type == 'Motorbike' else 15 if peak else 25
    return distance_km / speed * 60


def baseline_routes(orders, vehicles, depot=(21.0285,105.8542), peak=False):
    # Transparent baseline: sort by time-window start, then district, and fill vehicles by capacity.
    o=orders.copy()
    def tw_start(x):
        try:return int(str(x).split(':')[0])
        except:return 8
    o['_tw']=o['time_window'].map(tw_start)
    o=o.sort_values(['_tw','district','order_id']).drop(columns=['_tw'])
    routes=[]; idx=0
    for _,v in vehicles.iterrows():
        load=0; current=depot; stops=[]; duration=0; dist=0
        while idx<len(o):
            r=o.iloc[idx]; w=float(r.weight)
            if load+w>float(v.capacity): break
            d=haversine_km(current[0],current[1],r.lat,r.lon)*1.18
            t=travel_minutes(d,v.vehicle_type,peak)+float(r.service_min)
            if duration+t>600: break
            stops.append(r.order_id); load+=w; dist+=d; duration+=t; current=(r.lat,r.lon); idx+=1
        if stops:
            dist += haversine_km(current[0],current[1],depot[0],depot[1])*1.18
            routes.append(route_metrics(v,stops,o,dist,duration,load,depot))
        if idx>=len(o): break
    # If leftover, append overflow using final available vehicles (should be rare)
    while idx<len(o):
        r=o.iloc[idx]; v=vehicles.iloc[-1]; d=haversine_km(depot[0],depot[1],r.lat,r.lon)*1.18*2
        routes.append(route_metrics(v,[r.order_id],o,d,travel_minutes(d,v.vehicle_type,peak)+r.service_min,r.weight,depot)); idx+=1
    return pd.DataFrame(routes), o


def route_metrics(v, stops, orders, dist, duration, load, depot):
    typ=v.vehicle_type; fuel=dist*FUEL[typ]; cost=dist*COST_PER_KM[typ]; co2=fuel*EMISSION_FACTOR
    return dict(vehicle_id=v.vehicle_id, vehicle_type=typ, stops=stops, orders=len(stops), distance_km=dist,
                duration_min=duration, load_kg=load, capacity_kg=float(v.capacity), utilization_pct=100*load/float(v.capacity),
                fuel_l=fuel, cost_vnd=cost, co2_kg=co2)


def optimize_routes(orders, vehicles, alpha=0.6, peak=False, time_limit=8, depot=(21.0285,105.8542)):
    if not ORTOOLS_AVAILABLE:
        return heuristic_optimize(orders, vehicles, alpha, peak, depot), 'heuristic'
    n=len(orders); m=len(vehicles)
    # Scale to integer matrix. Geographic distance is a demo proxy; replace with road matrix for production.
    pts=[depot]+[(float(r.lat),float(r.lon)) for _,r in orders.iterrows()]
    base=np.zeros((n+1,n+1),dtype=int)
    for i in range(n+1):
        for j in range(n+1):
            if i!=j:
                base[i,j]=max(1,int(round(haversine_km(*pts[i],*pts[j])*1180)))
    manager=pywrapcp.RoutingIndexManager(n+1,m,0)
    routing=pywrapcp.RoutingModel(manager)
    # Cost proxy: distance weighted by average vehicle cost. Per-vehicle costs are incorporated after route extraction.
    avg_cost=np.mean([COST_PER_KM[x] for x in vehicles.vehicle_type])
    def dist_cb(i,j): return base[manager.IndexToNode(i),manager.IndexToNode(j)]
    transit=routing.RegisterTransitCallback(dist_cb); routing.SetArcCostEvaluatorOfAllVehicles(transit)
    # Capacity
    demands=[0]+[int(round(float(x))) for x in orders.weight]
    def dem_cb(i): return demands[manager.IndexToNode(i)]
    dcb=routing.RegisterUnaryTransitCallback(dem_cb)
    routing.AddDimensionWithVehicleCapacity(dcb,0,[int(x) for x in vehicles.capacity],True,'Capacity')
    # Time windows in minutes from 00:00. Vehicle-specific transit times.
    def parse_tw(s):
        a,b=str(s).split('-'); h1,m1=map(int,a.split(':')); h2,m2=map(int,b.split(':')); return h1*60+m1,h2*60+m2
    windows=[(0,1440)]+[parse_tw(x) for x in orders.time_window]
    service=[0]+[int(x) for x in orders.service_min]
    callbacks=[]
    for k in range(m):
        typ=vehicles.iloc[k].vehicle_type
        def make_cb(vehicle_type):
            def cb(i,j):
                ni,nj=manager.IndexToNode(i),manager.IndexToNode(j)
                travel=travel_minutes(base[ni,nj]/1180,vehicle_type,peak)
                return int(round(travel + (service[ni] if ni>0 else 0)))
            return cb
        callbacks.append(routing.RegisterTransitCallback(make_cb(typ)))
    # Use vehicle-specific transit callbacks for the Time dimension.
    # Bounds are explicitly cast/validated because OR-Tools requires integer
    # lower/upper bounds and raises a hard error when lower > upper.
    transit_indices = callbacks
    routing.AddDimensionWithVehicleTransits(transit_indices, 1440, 1440, False, 'Time')
    td = routing.GetDimensionOrDie('Time')
    for node in range(1, n + 1):
        idx = manager.NodeToIndex(node)
        a, b = windows[node]
        a, b = int(a), int(b)
        if a > b:
            a, b = b, a
        td.CumulVar(idx).SetRange(a, b)
    for k in range(m):
        td.CumulVar(routing.Start(k)).SetRange(0, 1440)
        td.CumulVar(routing.End(k)).SetRange(0, 1440)
    # Encourage fewer vehicles only mildly; distance remains main route structure.
    for k in range(m): routing.SetFixedCostOfVehicle(5000,k)
    search=pywrapcp.DefaultRoutingSearchParameters(); search.first_solution_strategy=routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search.local_search_metaheuristic=routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search.time_limit.seconds=int(time_limit)
    sol=routing.SolveWithParameters(search)
    if not sol:
        return heuristic_optimize(orders,vehicles,alpha,peak,depot), 'heuristic-fallback'
    out=[]
    for k in range(m):
        idx=routing.Start(k); stops=[]; dist=0; load=0; duration=0; prev=0
        while not routing.IsEnd(idx):
            node=manager.IndexToNode(idx)
            if node>0:
                r=orders.iloc[node-1]; stops.append(r.order_id); load+=float(r.weight); duration+=float(r.service_min)
            nxt=sol.Value(routing.NextVar(idx)); nnode=manager.IndexToNode(nxt)
            dist += base[node,nnode]/1180
            duration += travel_minutes(base[node,nnode]/1180,vehicles.iloc[k].vehicle_type,peak)
            idx=nxt
        if stops:
            out.append(route_metrics(vehicles.iloc[k],stops,orders,dist,duration,load,depot))
    return pd.DataFrame(out), 'ortools'


def heuristic_optimize(orders, vehicles, alpha=0.6, peak=False, depot=(21.0285,105.8542)):
    # Fast practical demo heuristic: time-window grouping + nearest neighbor + capacity.
    remaining=orders.copy(); routes=[]
    for _,v in vehicles.iterrows():
        if remaining.empty: break
        load=0; current=depot; stops=[]; dist=0; duration=0
        while not remaining.empty:
            candidates=[]
            for ix,r in remaining.iterrows():
                w=float(r.weight)
                if load+w>float(v.capacity): continue
                d=haversine_km(current[0],current[1],r.lat,r.lon)*1.18
                t=travel_minutes(d,v.vehicle_type,peak)+float(r.service_min)
                if duration+t<=600: candidates.append((d,ix,r))
            if not candidates: break
            _,ix,r=min(candidates,key=lambda x:x[0])
            d=haversine_km(current[0],current[1],r.lat,r.lon)*1.18
            dist+=d; duration+=travel_minutes(d,v.vehicle_type,peak)+float(r.service_min); load+=float(r.weight); stops.append(r.order_id); current=(r.lat,r.lon); remaining=remaining.drop(ix)
        if stops:
            back=haversine_km(current[0],current[1],depot[0],depot[1])*1.18; dist+=back; duration+=travel_minutes(back,v.vehicle_type,peak)
            routes.append(route_metrics(v,stops,orders,dist,duration,load,depot))
    return pd.DataFrame(routes)
