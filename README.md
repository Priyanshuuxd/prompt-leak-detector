# Prompt leak detector

This tool shows which outside companies receive what you type into a chatbot's web page.
Input: network logs (HAR files) that you save from your own browser after typing a test sentence with a made-up word, once after accepting cookies and once after rejecting them.
Output: `output/leaks.csv`, one row per outside company, with its category and whether it got your word after accepting and after rejecting.

## 1. Capture a log (guest mode, no login)

Do this twice: once clicking **Accept** on the cookie banner, once clicking **Reject**.

1. Open a **new private window** (so no earlier cookie choice is saved) and go to the chatbot without logging in.
2. Press **F12**, open the **Network** tab, tick **Preserve log**.
3. Click Accept (or Reject) on the cookie banner.
4. Type your test sentence, for example: `What is the best tea for a cold winter evening zebra7731quartz`. Use a made-up word that appears nowhere else. Do not type anything private.
5. Wait for the answer. Right-click in the request list and choose **Save all as HAR with content**. Name the files `accept.har` and `reject.har`.

A log can contain cookies and tokens. Keep it on your computer. `.gitignore` stops it from being committed.

## 2. Run the tool

```
python3 leak_finder.py zebra7731quartz --site chat.example --prompt "What is the best tea for a cold winter evening zebra7731quartz" --accept accept.har --reject reject.har
```

- `--site` is the chatbot's own address. Its requests are not counted. Add `--also other-address.example` for other addresses its company owns.
- `--prompt` is optional. With it the tool also finds the whole sentence when it is URL-encoded, base64 or hashed.
- `--trackers` points to a tracker list (columns `domain`, `company`, `category`). The default is `data/known_trackers.csv`. You can use the list from hello-world.

Try it on the fictional samples first:

```
python3 leak_finder.py zebra7731quartz --site chat.example --prompt "What is the best tea for a cold winter evening zebra7731quartz" --accept data/sample_accept.har --reject data/sample_reject.har
```

## 3. Check it yourself

In the Network tab press **Ctrl+Shift+F**, search for your word, and note which addresses show up. They should match the companies in `leaks.csv`. That is the check from issue #4.

## What it cannot see

- Data a company receives later from the chatbot's server instead of from your browser.
- Forms we do not search for: a hash of a part of the sentence, or text that is encrypted.
- Requests made after you saved the log.
- An empty result means "not seen in this log", not "no leak".

## Tests

```
python3 -m unittest -v
```

The checks in plain words are in `CHECKS.md`. The sample logs are fictional (`chat.example` is not a real chatbot).
