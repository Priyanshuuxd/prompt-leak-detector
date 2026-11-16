# Checks

Marker word: `zebra7731quartz`. Test sentence: `What is the best tea for a cold winter evening zebra7731quartz`.
The chatbot in the sample logs is the fictional `chat.example`.

On the sample logs:
- After accepting cookies, the tool finds 3 outside companies (doubleclick.net, hotjar.com, adnet-example.test).
- After rejecting cookies, it finds 1 (hotjar.com).
- The chatbot's own addresses (chat.example, api.chat.example) are never listed.
- adnet-example.test is marked unknown, because it is not on the tracker list.
- output/leaks.csv exists and has the columns site, company, category, after_accept, after_reject, found_as.

Finding the marker:
- It is found when it appears as plain text, URL-encoded, base64, hex, or as an md5, sha1 or sha256 hash.
- It is found when it is hidden inside a longer base64 string, at any position.
- A log without the marker gives no rows.
- A marker with fewer than 6 characters is refused.

My own check (from my issue #4):
- For a real chatbot, the companies the tool lists for my marker word match the requests I find myself by searching for that word in my browser's Network tab.
