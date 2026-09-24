import sys
print(sys.version)
for m in ['pandas','openpyxl','numpy','zipfile','lxml']:
 try:
  __import__(m); print(m,'OK')
 except Exception as e: print(m,'NO',type(e).__name__,e)
