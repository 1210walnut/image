import os
import uuid
import sqlite3
from datetime import datetime
from pathlib import Path
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from fastapi import (
    FastAPI,
    Request,
    UploadFile,
    File,
    Form,
    HTTPException
)

from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from PIL import Image


# =========================
# FastAPI 初期化
# =========================

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key="super-secret-key"
)


# =========================
# ディレクトリ自動生成
# =========================

Path("images").mkdir(exist_ok=True)
Path("thumbnails").mkdir(exist_ok=True)
Path("templates").mkdir(exist_ok=True)
Path("static").mkdir(exist_ok=True)


# =========================
# StaticFiles マウント
# =========================

app.mount("/images", StaticFiles(directory="images"), name="images")
app.mount("/thumbnails", StaticFiles(directory="thumbnails"), name="thumbnails")
app.mount("/static", StaticFiles(directory="static"), name="static")


# =========================
# Jinja2Templates 初期化
# =========================

templates = Jinja2Templates(directory="templates")


# =========================
# DB設定
# =========================

DB_NAME = "image_board.db"


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# =========================
# DB初期化
# =========================

def init_db():
    conn = get_db_connection()

    conn.execute("""
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    title TEXT NOT NULL,
    likes INTEGER DEFAULT 0,
    pinned INTEGER DEFAULT 0,
    created_at DATETIME NOT NULL
)
""")

    conn.execute("""
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    comment TEXT NOT NULL,
    pinned INTEGER DEFAULT 0,
    created_at DATETIME NOT NULL
)
""")
    conn.execute("""
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
)
""")
    conn.execute("""
INSERT OR IGNORE INTO admins(
    username,
    password
)
VALUES (?, ?)
""", (
    "admin",
    "password123"
))
    conn.commit()
    conn.close()


# 起動時にDB初期化
init_db()


# =========================
# 許可拡張子
# =========================

ALLOWED_EXTENSIONS = [".jpg", ".jpeg", ".png"]

# 5MB
MAX_FILE_SIZE = 5 * 1024 * 1024


# =========================
# サムネイル生成
# =========================

def create_thumbnail(image_path, thumbnail_path):
    with Image.open(image_path) as img:
        img.thumbnail((300, 300))
        img.save(thumbnail_path)


# =========================
# トップページ
# =========================

@app.get("/")
async def index(request: Request):

    conn = get_db_connection()

    images = conn.execute("""
        SELECT *
        FROM images
        ORDER BY pinned DESC,
         created_at DESC
    """).fetchall()

    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "images": images,
            "error": None
        }
    )


# =========================
# 投稿処理
# =========================

@app.post("/upload")
async def upload_image(
    request: Request,
    title: str = Form(...),
    file: UploadFile = File(...)
):

    try:

        # -------------------------
        # タイトルチェック
        # -------------------------

        title = title.strip()

        if not title:
            raise HTTPException(
                status_code=400,
                detail="タイトルを入力してください"
            )

        # -------------------------
        # 拡張子チェック
        # -------------------------

        original_filename = file.filename
        extension = os.path.splitext(original_filename)[1].lower()

        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail="jpg / png のみアップロード可能です"
            )

        # -------------------------
        # サイズチェック
        # -------------------------

        contents = await file.read()

        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail="ファイルサイズは5MB以下にしてください"
            )

        # -------------------------
        # UUIDファイル名生成
        # -------------------------

        unique_filename = f"{uuid.uuid4()}{extension}"

        image_path = os.path.join("images", unique_filename)
        thumbnail_path = os.path.join("thumbnails", unique_filename)

        # -------------------------
        # 保存
        # -------------------------

        with open(image_path, "wb") as f:
            f.write(contents)

        # -------------------------
        # Pillowで画像検証
        # -------------------------

        try:
            with Image.open(image_path) as img:
                img.verify()
        except Exception:
            os.remove(image_path)

            raise HTTPException(
                status_code=400,
                detail="不正な画像ファイルです"
            )

        # -------------------------
        # サムネイル生成
        # -------------------------

        create_thumbnail(image_path, thumbnail_path)

        # -------------------------
        # DB保存
        # -------------------------

        conn = get_db_connection()

        conn.execute("""
            INSERT INTO images (
                filename,
                title,
                created_at
            )
            VALUES (?, ?, ?)
        """, (
            unique_filename,
            title,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        conn.commit()
        conn.close()

        # 投稿後リダイレクト
        return RedirectResponse(
            url="/",
            status_code=303
        )

    except HTTPException as e:

        conn = get_db_connection()

        images = conn.execute("""
            SELECT *
            FROM images
            ORDER BY pinned DESC,
         created_at DESC
        """).fetchall()

        conn.close()

        return templates.TemplateResponse(
    request=request,
    name="index.html",
    context={
        "request": request,
        "images": images,
        "error": e.detail
    }
)

    except Exception as e:

        conn = get_db_connection()

        images = conn.execute("""
            SELECT *
            FROM images
            ORDER BY pinned DESC,
         created_at DESC
        """).fetchall()

        conn.close()

        return templates.TemplateResponse(
    request=request,
    name="index.html",
    context={
        "request": request,
        "images": images,
        "error": e.detail
    }
)

# =========================
# 詳細ページ
# =========================

@app.get("/image/{image_id}")
async def image_detail(request: Request, image_id: int):

    conn = get_db_connection()

    image = conn.execute(
        """
        SELECT *
        FROM images
        WHERE id = ?
        """,
        (image_id,)
    ).fetchone()

    comments = conn.execute("""
SELECT *
FROM comments
WHERE image_id = ?
ORDER BY pinned DESC,
         created_at DESC
""", (image_id,)).fetchall()
    conn.close()

    if image is None:
        raise HTTPException(
            status_code=404,
            detail="画像が見つかりません"
        )

    return templates.TemplateResponse(
        request=request,
        name="detail.html",
        context={
    "request": request,
    "image": image,
    "comments": comments
}
    )

@app.post("/image/{image_id}/comment")
async def add_comment(
    image_id: int,
    username: str = Form(...),
    comment: str = Form(...)
):

    conn = get_db_connection()

    conn.execute("""
        INSERT INTO comments (
            image_id,
            username,
            comment,
            created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        image_id,
        username,
        comment,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    conn.close()

    return RedirectResponse(
        url=f"/image/{image_id}",
        status_code=303
    )
# =========================
# 起動確認用
# =========================
@app.get("/admin/login")
async def admin_login_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context={
            "request": request
        }
    )

@app.post("/admin/login")
async def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):

    conn = get_db_connection()

    admin = conn.execute("""
        SELECT *
        FROM admins
        WHERE username = ?
        AND password = ?
    """, (
        username,
        password
    )).fetchone()

    conn.close()

    if admin is None:
        return RedirectResponse(
            "/admin/login",
            status_code=303
        )

    request.session["admin"] = True

    return RedirectResponse(
        "/",
        status_code=303
    )

@app.get("/admin/logout")
async def logout(request: Request):

    request.session.clear()

    return RedirectResponse(
        "/",
        status_code=303
    )

@app.post("/image/{image_id}/like")
async def like_image(image_id: int):

    conn = get_db_connection()

    conn.execute("""
        UPDATE images
        SET likes = likes + 1
        WHERE id = ?
    """, (image_id,))

    conn.commit()
    conn.close()

    return RedirectResponse(
        f"/image/{image_id}",
        status_code=303
    )

@app.post("/image/{image_id}/pin")
async def pin_image(
    request: Request,
    image_id: int
):

    if not request.session.get("admin"):
        raise HTTPException(
            status_code=403,
            detail="管理者専用"
        )

    conn = get_db_connection()

    conn.execute("""
        UPDATE images
        SET pinned = 1
        WHERE id = ?
    """, (image_id,))

    conn.commit()
    conn.close()

    return RedirectResponse(
        f"/image/{image_id}",
        status_code=303
    )

@app.post("/image/{image_id}/unpin")
async def unpin_image(
    request: Request,
    image_id: int
):

    if not request.session.get("admin"):
        raise HTTPException(
            status_code=403,
            detail="管理者専用"
        )

    conn = get_db_connection()

    conn.execute("""
        UPDATE images
        SET pinned = 0
        WHERE id = ?
    """, (image_id,))

    conn.commit()
    conn.close()

    return RedirectResponse(
        f"/image/{image_id}",
        status_code=303
    )

@app.post("/comment/{comment_id}/pin")
async def pin_comment(
    request: Request,
    comment_id: int
):

    if not request.session.get("admin"):
        raise HTTPException(
            status_code=403,
            detail="管理者専用"
        )

    conn = get_db_connection()

    conn.execute("""
        UPDATE comments
        SET pinned = 1
        WHERE id = ?
    """, (comment_id,))

    conn.commit()
    conn.close()

    return RedirectResponse(
        request.headers.get("referer", "/"),
        status_code=303
    )


@app.post("/comment/{comment_id}/unpin")
async def unpin_comment(
    request: Request,
    comment_id: int
):

    if not request.session.get("admin"):
        raise HTTPException(
            status_code=403,
            detail="管理者専用"
        )

    conn = get_db_connection()

    conn.execute("""
        UPDATE comments
        SET pinned = 0
        WHERE id = ?
    """, (comment_id,))

    conn.commit()
    conn.close()

    return RedirectResponse(
        request.headers.get("referer", "/"),
        status_code=303
    )

@app.post("/comment/{comment_id}/delete")
async def delete_comment(
    request: Request,
    comment_id: int
):

    if not request.session.get("admin"):
        raise HTTPException(
            status_code=403,
            detail="管理者専用"
        )

    conn = get_db_connection()

    conn.execute("""
        DELETE FROM comments
        WHERE id = ?
    """, (comment_id,))

    conn.commit()
    conn.close()

    return RedirectResponse(
        request.headers.get("referer", "/"),
        status_code=303
    )

@app.post("/image/{image_id}/delete")
async def delete_image(
    request: Request,
    image_id: int
):

    if not request.session.get("admin"):
        raise HTTPException(
            status_code=403,
            detail="管理者専用"
        )

    conn = get_db_connection()

    image = conn.execute("""
        SELECT *
        FROM images
        WHERE id = ?
    """, (image_id,)).fetchone()

    if image:

        image_path = os.path.join(
            "images",
            image["filename"]
        )

        thumbnail_path = os.path.join(
            "thumbnails",
            image["filename"]
        )

        if os.path.exists(image_path):
            os.remove(image_path)

        if os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)

        conn.execute("""
            DELETE FROM comments
            WHERE image_id = ?
        """, (image_id,))

        conn.execute("""
            DELETE FROM images
            WHERE id = ?
        """, (image_id,))

    conn.commit()
    conn.close()

    return RedirectResponse(
        "/",
        status_code=303
    )

@app.get("/about")
async def about_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="about_me.html",
        context={
            "request": request
        }
    )


@app.get("/terms")
async def terms_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="terms.html",
        context={
            "request": request
        }
    )
    
@app.get("/health")
async def health():
    return {"status": "ok"}