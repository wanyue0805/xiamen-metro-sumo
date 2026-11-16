"""Simulation depot catalogue shared by dispatch logic and visual renderers.

The facilities are designed for the project's schematic rail network. They are
not surveyed Xiamen depots. Live occupancy uses actual engine train readings;
this module never invents parked trains or calls TraCI during rendering.
"""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parent
CATALOGUE_PATH=ROOT/'network/depot.catalogue.json'

def catalogue():
    if not CATALOGUE_PATH.exists():return []
    return json.loads(CATALOGUE_PATH.read_text(encoding='utf-8')).get('depots',[])

class DepotManager:
    def __init__(self,engine=None):
        self.engine=engine
        self.depots=catalogue()
        self.by_id={depot['id']:depot for depot in self.depots}
        self.by_terminal={(int(depot['line']),depot['direction']):depot for depot in self.depots}

    def get_depot(self,line,direction):
        return self.by_terminal[(int(line),str(direction))]

    def departure_route(self,line,direction,sequence=0):
        depot=self.get_depot(line,direction)
        return depot['tracks'][int(sequence)%len(depot['tracks'])]['route_id']

    def departure(self,line,direction,sequence=0):
        depot=self.get_depot(line,direction)
        track=depot['tracks'][int(sequence)%len(depot['tracks'])]
        return dict(depot_id=depot['id'],track_id=track['id'],route_id=track['route_id'],
                    edge=track['edge'],depart_pos=140,exit_signal=track['exit_signal'],
                    speed_limit_mps=track['speed_limit_mps'])

    def choose_spawn(self,line,direction):
        depot=self.get_depot(line,direction)
        trains=getattr(self.engine,'trains',{}).values()
        holders={track['id']:set() for track in depot['tracks']}
        for train in trains:
            # The origin track may remain in a train's history after departure;
            # it must not occupy storage while the vehicle runs on the mainline.
            tracked=train.get('edge','') if train.get('active') else train.get('depot_track','')
            if tracked in holders:holders[tracked].add(train['id'])
            if train.get('depot_phase') in ('入段','已入段') and train.get('depot_track') in holders:
                holders[train['depot_track']].add(train['id'])
        # A future terminal return is a real capacity reservation even before
        # the vehicle reaches the depot. Sets prevent counting the same train
        # twice when its physical track and its target happen to coincide.
        for vid,request in getattr(self.engine,'_depot_requests',{}).items():
            if request.get('track_id') in holders:holders[request['track_id']].add(vid)
        counts={ident:len(vehicles) for ident,vehicles in holders.items()}
        sequence=getattr(self,'_sequence',0);self._sequence=sequence+1
        ordered=depot['tracks'][sequence%3:]+depot['tracks'][:sequence%3]
        track=min(ordered,key=lambda item:counts[item['id']])
        if counts[track['id']]>=track['capacity_trains']:
            return None
        return dict(depot_id=depot['id'],track_id=track['id'],route_id=track['route_id'],
                    edge=track['edge'],depart_pos=140,exit_signal=track['exit_signal'],
                    speed_limit_mps=track['speed_limit_mps'])

    def tick(self,frame=None):
        # Engine owns subscription readings and updates its actual train cache.
        # No per-vehicle TraCI polling is introduced here.
        return self.snapshot()

    def entry_route(self,line,direction,track=0):
        return self.get_depot(line,direction)['tracks'][int(track)%3]['entry_route_id']

    def locate(self,edge):
        edge=edge.lstrip(':')
        for depot in self.depots:
            if edge.startswith(depot['id']+'_') or edge==depot['base_edge']:
                return depot
        return None

    def snapshot(self,trains=None):
        if trains is None:trains=getattr(self.engine,'trains',{})
        values=trains.values() if isinstance(trains,dict) else trains
        active=[train for train in values if train.get('active')]
        result=[]
        for depot in self.depots:
            present=[train for train in active if train.get('edge','').lstrip(':').startswith(depot['id']+'_')]
            tracks=[]
            for track in depot['tracks']:
                occupants=[train['id'] for train in present if train.get('edge')==track['edge']]
                tracks.append({**track,'occupied':len(occupants),'train_ids':occupants})
            result.append({**depot,'tracks':tracks,'live_train_ids':[train['id'] for train in present],
                           'occupied_tracks':sum(bool(track['occupied']) for track in tracks)})
        return result
