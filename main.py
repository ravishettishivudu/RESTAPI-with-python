from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.responses import HTMLResponse
from typing import Optional, List
from sqlmodel import SQLModel, Field, create_engine, Session, select
from datetime import datetime, date
from pydantic import BaseModel, constr
from contextlib import asynccontextmanager

# --- Database setup (SQLite for dev) ---
DATABASE_URL = "sqlite:///./tasks.db"
engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})

# --- Models ---
class TaskBase(SQLModel):
    title: constr(strip_whitespace=True, min_length=1, max_length=200)
    description: Optional[str] = None
    done: bool = False
    priority: Optional[int] = 3  # 1 highest, 5 lowest
    due_date: Optional[date] = None

class Task(TaskBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class TaskCreate(TaskBase):
    pass

class TaskRead(TaskBase):
    id: int
    created_at: datetime

class TaskUpdate(BaseModel):
    title: Optional[constr(strip_whitespace=True, min_length=1, max_length=200)] = None
    description: Optional[str] = None
    done: Optional[bool] = None
    priority: Optional[int] = None
    due_date: Optional[date] = None

# --- Create DB tables ---
def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="Task Manager API", version="1.0", lifespan=lifespan)

# Dependency to get DB session
def get_session():
    with Session(engine) as session:
        yield session

# --- CRUD Endpoints ---
@app.post("/tasks/", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(*, session: Session = Depends(get_session), task: TaskCreate):
    db_task = Task.from_orm(task)
    session.add(db_task)
    session.commit()
    session.refresh(db_task)
    return db_task

@app.get("/tasks/", response_model=List[TaskRead])
def list_tasks(
    *,
    session: Session = Depends(get_session),
    q: Optional[str] = None,
    done: Optional[bool] = None,
    priority: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
):
    query = select(Task)
    if q:
        query = query.where(Task.title.contains(q) | Task.description.contains(q))
    if done is not None:
        query = query.where(Task.done == done)
    if priority is not None:
        query = query.where(Task.priority == priority)
    query = query.offset(offset).limit(limit)
    results = session.exec(query).all()
    return results

@app.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(*, session: Session = Depends(get_session), task_id: int):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@app.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(*, session: Session = Depends(get_session), task_id: int, task_in: TaskUpdate):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task_data = task_in.dict(exclude_unset=True)
    for key, value in task_data.items():
        setattr(task, key, value)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task

@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(*, session: Session = Depends(get_session), task_id: int):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    session.delete(task)
    session.commit()
    return

# --- Health endpoint ---
@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

# --- Default Root -> UI ---
@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Task Manager UI</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            input, button { padding: 6px; margin: 4px; }
            .task { border: 1px solid #ccc; padding: 10px; margin: 5px; border-radius: 6px; }
            .done { text-decoration: line-through; color: gray; }
        </style>
    </head>
    <body>
        <h2>Task Manager</h2>
        <div>
            <input id="title" placeholder="Task title">
            <input id="desc" placeholder="Description">
            <button onclick="addTask()">Add Task</button>
        </div>
        <h3>Tasks</h3>
        <div id="tasks"></div>

        <script>
            async function fetchTasks() {
                let res = await fetch("/tasks/");
                let data = await res.json();
                let container = document.getElementById("tasks");
                container.innerHTML = "";
                data.forEach(t => {
                    let div = document.createElement("div");
                    div.className = "task" + (t.done ? " done" : "");
                    div.innerHTML = `
                        <b>${t.title}</b> - ${t.description || ""} 
                        [Done: ${t.done}] 
                        <button onclick="toggleDone(${t.id}, ${t.done})">${t.done ? "Undo" : "Mark Done"}</button>
                        <button onclick="editTask(${t.id}, '${t.title}', '${t.description || ""}')">Edit</button>
                        <button onclick="deleteTask(${t.id})">Delete</button>
                    `;
                    container.appendChild(div);
                });
            }

            async function addTask() {
                let title = document.getElementById("title").value;
                let desc = document.getElementById("desc").value;
                if (!title) { alert("Title is required"); return; }
                await fetch("/tasks/", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({title: title, description: desc})
                });
                document.getElementById("title").value = "";
                document.getElementById("desc").value = "";
                fetchTasks();
            }

            async function deleteTask(id) {
                await fetch("/tasks/" + id, { method: "DELETE" });
                fetchTasks();
            }

            async function toggleDone(id, current) {
                await fetch("/tasks/" + id, {
                    method: "PATCH",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({done: !current})
                });
                fetchTasks();
            }

            async function editTask(id, oldTitle, oldDesc) {
                let newTitle = prompt("Edit title:", oldTitle);
                if (newTitle === null) return;
                let newDesc = prompt("Edit description:", oldDesc);
                await fetch("/tasks/" + id, {
                    method: "PATCH",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({title: newTitle, description: newDesc})
                });
                fetchTasks();
            }

            fetchTasks();
        </script>
    </body>
    </html>
    """

# --- Run server ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
