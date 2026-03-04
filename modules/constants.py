import os
#from dotenv import load_dotenv
#load_dotenv()

supabase_db_host = os.getenv("SUPABASE_DB_HOST_URL", "aws-0-us-west-2.pooler.supabase.com")
supabase_db_password = os.getenv("SUPABASE_DB_PASSWORD")
database_pool_size_str = os.getenv("DATABASE_POOL_SIZE")

