# Use the pure-Python PyMySQL driver as Django's MySQL driver (no C compiler needed on the server).
import pymysql

pymysql.install_as_MySQLdb()
