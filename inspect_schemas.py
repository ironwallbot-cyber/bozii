from bozii.schemas import CapabilityOut, TaskOut, TaskDetail
print('CapabilityOut:', [f.alias or f.name for f in CapabilityOut.model_fields.values()])
print('TaskOut:', [f.alias or f.name for f in TaskOut.model_fields.values()])
print('TaskDetail:', [f.alias or f.name for f in TaskDetail.model_fields.values()])
