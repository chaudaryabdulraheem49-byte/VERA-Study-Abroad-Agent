import urllib.request
import urllib.parse
import json

tests = ['Medicine', 'Dentistry', 'Surgery', 'Management', 'Design', 'Physics', 'MBBS']
for t in tests:
    encoded = urllib.parse.quote(t)
    url = f"http://localhost:3000/api/discovery?country=Canada&limit=5&field_broad={encoded}"
    try:
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            courses = data.get('courses', [])
            print(f"[API Search: {t:<10}] Found: {len(courses)} results (limit=5)")
            for c in courses[:2]:
                print(f"   * {c['course_title']} ({c['university_name']}) - {c['degree_level']}")
    except Exception as e:
        print(f"[API Search: {t:<10}] Error: {e}")
