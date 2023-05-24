# Copyright (c) 2021 by ERIGrid 2.0. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.

from itertools import count
from .simulator import DHNetwork
from mosaik_api import Simulator
from typing import Dict

META = {
    'type': 'hybrid',
    'models': {
        'DHNetwork': {
            'public': True,
            'params': [
                'T_amb',  # Ambient ground temperature
                'enable_logging',
                'T_supply_grid',
                'P_grid_bar',
                'dynamic_temp_flow_enabled',
                ],
            'attrs': [
                # Input
                'T_tank_forward',  # Supply temp of storage unit
                'mdot_tank_in_set',  # Mass flow injected by tank
                'mdot_grid_set',  # Mass flow injected by the grid
                'mdot_cons1_set',  # Mass flow at consumer 1
                'mdot_cons2_set',  # Mass flow at consumer 2
                'Qdot_evap',  # Heat consumption of heat pump evaporator
                'Qdot_cons1',  # Heat consumption of consumer 1
                'Qdot_cons2',  # Heat consumption of consumer 2
                # Output
                'T_supply_grid',  # Supply temperature of the external grid
                'T_return_grid',  # Return temperature of the external grid
                'T_return_tank',  # Return temperature of the storage unit
                'T_evap_in',  # Return temperature towards the heat pump evaporator
                'T_supply_cons1',  # Supply temperature at consumer 1
                'T_supply_cons2',  # Supply temperature at consumer 2
                'T_return_cons1',  # Return temperature at consumer 1
                'T_return_cons2',  # Return temperature at consumer 2
                'mdot_tank_in',  # Mass flow injected by tank
                'mdot_grid',  # Mass flow injected by the grid
                'mdot_cons1',  # Mass flow at consumer 1
                'mdot_cons2',  # Mass flow at consumer 2
                'initialized',  # is the initialization finished?
                ],
            'trigger': ['T_tank_forward', 'Qdot_evap'],
            # 'trigger': ['mdot_cons1_set', 'mdot_cons2_set', 'T_tank_forward'],
            # 'non-persistent': ['T_supply_cons1', 'T_supply_cons2'],
            'non-persistent': ['T_return_tank']
            },
        },
    }


class DHNetworkSimulator(Simulator):

    step_size = 10
    eid_prefix = ''
    last_time = 0

    def __init__(self, META=META):
        super().__init__(META)

        # Per-entity dicts
        self.eid_counters = {}
        self.simulators: Dict[DHNetwork] = {}
        self.entityparams = {}
        self.output_vars = {'T_return_tank', 'T_evap_in', 'T_return_grid', 'T_supply_cons1', 'T_supply_cons2', 'T_return_cons1', 'T_return_cons2',
                            'mdot_tank_in', 'mdot_grid', 'mdot_cons1', 'mdot_cons2', 'initialized'}
        self.input_vars = {'mdot_grid_set', 'T_tank_forward', 'mdot_tank_in_set', 'mdot_cons1_set', 'mdot_cons2_set', 'Qdot_evap', 'Qdot_cons1', 'Qdot_cons2'}
        self.init_dict = {}
        self.init_attrs = ['T_tank_forward', 'Qdot_evap']
        #TODO: add multiple variables for multiple models?
        self.init_finished = {}
        self.all_init_finished = False

    def init(self, sid, time_resolution, step_size=10, eid_prefix="DHNetwork"):
        self.step_size = step_size
        self.eid_prefix = eid_prefix

        return self.meta


    def create(self, num, model, **model_params):
        counter = self.eid_counters.setdefault(model, count())
        entities = []

        for _ in range(num):

            eid = '%s_%s' % (self.eid_prefix, next(counter))
            if eid not in self.init_finished:
                self.init_finished[eid] = {}
            for attr in self.init_attrs:
                self.init_finished[eid][attr] = False
            self.init_dict[eid] = {}

            self.entityparams[eid] = model_params
            esim = DHNetwork(**model_params)

            self.simulators[eid] = esim

            entities.append({'eid': eid, 'type': model})

        return entities


    def step(self, time, inputs, max_advance):
        self.last_time = time
        # if time < 200:
        #     print('dh network step: %s - %s' % (time, inputs))

        for eid, esim in self.simulators.items():
            data = inputs.get(eid, {})
            for attr, incoming in data.items():
                if attr in self.input_vars:

                    if 1 != len(incoming):
                        raise RuntimeError('DHNetworkSimulator does not support multiple inputs')

                    newval = None

                    if list(incoming.values())[0] is not None:
                        if 'mdot' in attr:
                            newval = -list(incoming.values())[0]  # Reverse the sign of incoming mass flow values
                        else:
                            newval = list(incoming.values())[0]
                        setattr(esim, attr, newval)
                    else:
                        print(f'input is None for {attr}')

                    if time == 0 and attr in self.init_attrs:
                        if attr not in self.init_finished[eid]:
                            self.init_finished[eid][attr] = False
                        if attr not in self.init_dict[eid]:
                            self.init_dict[eid][attr] = []
                        if newval:
                            self.init_dict[eid][attr].append(newval)
                        else:
                            # print(f'0 ({attr})')
                            self.init_dict[eid][attr].append(0)

                else:
                    raise AttributeError(f"DHNetworkSimulator {eid} has no input attribute {attr}.")

            esim.step_single(time)

            # Check if initialization is finished
            if time == 0:
                delta = 0.01
                for attr, y in self.init_dict[eid].items():
                    if attr in self.init_attrs and y and len(y) > 5:
                        if abs(y[-2] - y[-1]) < delta:
                            if not self.init_finished[eid][attr]:
                                print('     dh network: Attribute %s has a smaller delta to previous value '
                                      'than %s after %s same time loops.' % (attr, delta, len(y)))
                            self.init_finished[eid][attr] = True
                    if y and len(y) > 1950:
                        print('     dh network: No convergence after 1950 same time loops.')
                        self.init_finished[eid][attr] = True

        if not self.all_init_finished:
            tmp_all_init_finished = True
            for eid in self.init_finished:
                for attr, initialized in self.init_finished[eid].items():
                    if not initialized:
                        tmp_all_init_finished = False
            if not tmp_all_init_finished:
                return None
            else:
                self.all_init_finished = True
        return time + self.step_size

    def get_data(self, outputs):
        if self.all_init_finished:
            data = {'time': self.last_time + self.step_size}
        elif self.last_time == 0:
            data = {'time': self.last_time}
        else:
            data = {}

        for eid, esim in self.simulators.items():
            requests = outputs.get(eid, [])
            mydata = {}

            for attr in requests:
                if attr in self.input_vars or attr in self.output_vars:
                    if attr == 'initialized':
                        mydata[attr] = self.init_finished[eid]
                    else:
                        mydata[attr] = getattr(esim, attr)
                else:
                    raise AttributeError(f"DHNetworkSimulator {eid} has no attribute {attr}.")

            data[eid] = mydata

        # if self.last_time < 200:
        # s    print('dh network get_data: %s' % data)

        return data


if __name__ == '__main__':

    test = DHNetworkSimulator()
