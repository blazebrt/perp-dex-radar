"""Independent structural reader for A6 compact pair records.

No encoder imports. Reconstructs evidence only; semantic audits remain mandatory.
"""
import copy
import json


def require(value,message):
    if not value:raise ValueError(message)


def expand(value,count):
    require(type(value) is dict and set(value)=={'shared','columns','rows'},'invalid table envelope')
    shared,columns,rows=value['shared'],value['columns'],value['rows']
    require(type(shared) is dict and all(type(k) is str for k in shared),'invalid shared fields')
    require(type(columns) is list and all(type(k) is str for k in columns),'invalid columns')
    require(len(set(columns))==len(columns) and not set(columns)&set(shared),'ambiguous columns')
    require(type(rows) is list and len(rows)==count,'table row count mismatch')
    result=[]
    for values in rows:
        require(type(values) is list and len(values)==len(columns),'table width mismatch')
        row=copy.deepcopy(shared)
        for index,name in enumerate(columns):row[name]=copy.deepcopy(values[index])
        result.append(row)
    return result


def unpack(record):
    require(type(record) is dict and set(record)=={'schema','base','outcomes','features'},'invalid packed envelope')
    require(record['schema']=='v9.a6-packed-pair/1','unknown packed schema')
    # Reject non-JSON numeric values before they reach later arithmetic checks.
    json.dumps(record,allow_nan=False)
    base=copy.deepcopy(record['base'])
    require(type(base) is dict and 'candidate' not in base,'invalid pair base')
    controls=base.get('controls');cohort=base.get('cohort')
    require(type(controls) is list and type(cohort) is dict and type(cohort.get('controls')) is list,'missing controls')
    selection=cohort['controls']
    require(len(controls)<=50 and len(selection)==len(controls),'invalid control population')
    require(all(type(row) is dict and 'outcome' not in row for row in controls),'duplicate outcome storage')
    require(all(type(row) is dict and 'features' not in row for row in selection),'duplicate feature storage')
    outcomes=expand(record['outcomes'],len(controls)+1)
    features=expand(record['features'],len(selection))
    base['candidate']=outcomes[0]
    for i,row in enumerate(controls):row['outcome']=outcomes[i+1]
    for i,row in enumerate(selection):row['features']=features[i]
    return base
