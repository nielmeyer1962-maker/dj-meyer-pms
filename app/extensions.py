from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
login_manager = LoginManager()
# Anonymous users hitting a guarded view are sent here. The global before_request gate
# also redirects, but setting this keeps Flask-Login's own helpers consistent.
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"
