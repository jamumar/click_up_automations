from fastapi import FastAPI
from api.status_change import router as status_router
from api.task_created import router as task_created_router 
from api.subtask_created import router as subtask_created_router
from api.custom_field_changed import router as custom_field_router
from api.subtask_status_changed import router as subtask_status_changed_router

app = FastAPI()

app.include_router(status_router)
app.include_router(task_created_router) 
app.include_router(subtask_created_router)  
app.include_router(custom_field_router)
app.include_router(subtask_status_changed_router)

