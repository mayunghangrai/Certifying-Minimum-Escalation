from recovery_cases import worked


def tiny():
    p = worked('B')
    p['mission']['tasks'] = p['mission']['tasks'][:1]
    p['mission']['tasks'][0]['deadline_h'] = 3
    p['mission']['vehicles'] = p['mission']['vehicles'][:1]
    p['state']['fleet'] = {'U1':p['state']['fleet']['U1']}
    p['state']['cumulative_delivered'] = {'T1':0}
    p['incumbent']['assignment'] = {'T1':'U1'}
    p['incumbent']['routes'] = {'U1':p['incumbent']['routes']['U1']}
    p['reserve_paths'] = {'U1':p['reserve_paths']['U1']}
    p['commitments'] = {a:[key for key in keys if key.startswith('U1:')]
                        for a,keys in p['commitments'].items()}
    p['commitments']['L'] = []
    return p
