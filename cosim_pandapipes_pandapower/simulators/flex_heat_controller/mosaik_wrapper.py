# Copyright (c) 2021 by ERIGrid 2.0. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be found in the LICENSE file.
'''
Model of the power-to-heat facility controller.
'''

from itertools import count
from .simulator import SimpleFlexHeatController
from mosaik_api import Simulator
from typing import Dict

META = {
    'type': 'hybrid',
    'models': {
        'SimpleFlexHeatController': {
            'public': True,
            'params': ['voltage_control_enabled'],
            'attrs': [
                # Input
                'mdot_HEX1', 'mdot_HEX2', 'T_tank_hot', 'T_hp_cond_in', 'T_hp_cond_out', 'T_hp_evap_in', 'T_hp_evap_out',
                'P_hp_el_setpoint', 'P_hp_effective', 'initialized',
                # Output
                'mdot_1_supply', 'mdot_2_supply', 'mdot_3_supply',
                'mdot_1_return', 'mdot_2_return', 'mdot_3_return',
                'Q_HP_set', 'mdot_HP_out', 'mdot_tank_in',
                'hp_on_request', 'hp_off_request', 'state'
                ],
            'trigger': ['P_hp_effective', 'T_hp_cond_out', 'T_hp_cond_in', 'T_hp_evap_in', 'mdot_HEX1', 'mdot_HEX2'],
            'non-persistent': ['Q_HP_set', 'mdot_HP_out', 'mdot_2_return', 'mdot_3_supply'],
            },
        },
    }


class SimpleFlexHeatControllerSimulator(Simulator):

    step_size = 10
    eid_prefix = ''
    last_time = 0

    def __init__(self, META=META):
        super().__init__(META)

        # Per-entity dicts
        self.eid_counters = {}
        self.simulators: Dict[SimpleFlexHeatController] = {}
        self.entityparams = {}
        self.output_vars = {'mdot_1_supply', 'mdot_2_supply', 'mdot_3_supply', 'mdot_1_return', 'mdot_2_return', 'mdot_3_return', 'Q_HP_set', 'mdot_HP_out', 'mdot_tank_in', 'hp_on_request', 'hp_off_request', 'state'}
        self.input_vars = {'mdot_HEX1', 'mdot_HEX2', 'T_tank_hot', 'T_hp_cond_in', 'T_hp_cond_out', 'T_hp_evap_in', 'T_hp_evap_out', 'P_hp_el_setpoint', 'P_hp_effective', 'initialized'}
        self.init_dict = {}
        self.init_attrs = ['P_hp_effective', 'T_hp_cond_out', 'T_hp_cond_in', 'T_hp_evap_in']
        #TODO: add multiple variables for multiple models?
        self.init_finished = {}
        self.all_init_finished = False

    def init(self, sid, time_resolution, step_size=10, eid_prefix="FHctrl"):
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
            esim = SimpleFlexHeatController(**model_params)

            self.simulators[eid] = esim

            entities.append({'eid': eid, 'type': model})

        return entities


    def step(self, time, inputs, max_advance):
        self.last_time = time
        # if time < 200:
        #     print('flex controller step: %s - %s' % (time, inputs))

        for eid, esim in self.simulators.items():
            data = inputs.get(eid, {})
            for attr, incoming in data.items():
                if attr in self.input_vars:
                    if 1 != len(incoming):
                        raise RuntimeError('SimpleFlexHeatControllerSimulator does not support multiple inputs')

                    newval = None

                    if list(incoming.values())[0] is not None:
                        if 'mdot' in attr:
                            newval = -list(incoming.values())[0] # Reverse the sign of incoming mass flow values
                        else:
                            newval = list(incoming.values())[0]
                        setattr(esim, attr, newval)

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
                    raise AttributeError(f"SimpleFlexHeatControllerSimulator {eid} has no input attribute {attr}.")

            esim.step_single()

            # Check if initialization is finished
            if time == 0:
                delta = 0.001
                for attr, y in self.init_dict[eid].items():
                    if attr in self.init_attrs and y and len(y) > 5:
                        if abs(y[-2] - y[-1]) < delta:
                            if not self.init_finished[eid][attr]:
                                print('     flex controller: Attribute %s has a smaller delta to previous value '
                                      'than %s after %s same time loops.' % (attr, delta, len(y)))
                            self.init_finished[eid][attr] = True
                    if y and len(y) > 1000:
                        # print('     flex controller: No convergence after 1000 same time loops.')
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
        # return None

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
                    mydata[attr] = getattr(esim, attr)
                else:
                    raise AttributeError(f"SimpleFlexHeatControllerSimulator {eid} has no attribute {attr}.")

            data[eid] = mydata

        # if self.last_time < 200:
        #     print('flex controller get_data: %s' % data)

        return data


if __name__ == '__main__':

    test = SimpleFlexHeatControllerSimulator()
