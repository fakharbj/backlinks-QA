# LinkSentinel — Canonical link types & sheet standard

> **Single source of truth for link-type / sub-sheet names.**
> Every project sheet **tab name IS a link type** — the sync copies the tab name
> straight onto every link in that tab. So "clean tab names" = "clean link types".
> Use **only** the names below. One tab per link type. Nothing else to memorise.

Adopted 2026-07-21. Owner sign-off: "adopt as proposed". Historical data is
**never lost** — old/misspelled names are merged into the canonical name via the
catalog's alias chain, so every existing backlink keeps resolving.

---

## 1. The canonical list (19)

### Standard link types (14)

| Canonical name | What goes here |
|---|---|
| **Social Bookmarking** | Bookmarking sites (Reddit-style saves, Mix, Pocket, etc.). |
| **Web 2.0** | Free hosted blogs / properties (WordPress.com, Blogger, Medium, Tumblr…). |
| **Article Submission** | Article-directory / content-submission sites. |
| **Blog Post** | Blog posts on third-party blogs (not a paid guest post). |
| **Guest Post** | Editorial placements on someone else's site (paid or outreach). |
| **Business Listing** | Directories & citation sites (non-Google): Yelp, Yellow Pages, niche dirs. |
| **Profile** | Profile-creation links (a bio/profile page carrying the link). |
| **Profile & Forums** | Forum posts / signatures and combined profile+forum work. |
| **Image Submission** | Image-sharing / pin sites where the link sits on an image asset. |
| **PDF Submission** | Document/PDF-sharing sites (Scribd, SlideShare, Issuu…). |
| **Classified Ads** | Classified-ad posting sites. |
| **Wiki Submission** | Wiki-style contribution links. |
| **Social Media** | Social-network posts/profiles carrying the link. |
| **Q&A & Content Sharing** | Q&A + mixed content sharing (Quora, Pinterest, Reddit, video, etc.). |

### Google Business Profile family (5)

> Use these for GBP/GMB campaigns. They get relaxed link-matching in QA
> (`RELAXED_MATCH_LINK_TYPE_SUBSTRINGS=gbp,gmb`), so keep the **`GBP – `** prefix.

| Canonical name | What goes here |
|---|---|
| **GBP – Article** | Article-type links built for a Google Business Profile. |
| **GBP – Web 2.0** | Web 2.0 links built for a GBP. |
| **GBP – Citation** | Citation links for a GBP. |
| **GBP – Business Listing** | Business-listing / GMB listing links for a GBP. |
| **GBP – Maps** | Google Maps listing links. |

**Not link types (do not create tabs for these):** `Indexing Work` (a task, not a
placement), and any `ZZTest…` rows (test junk — delete).

---

## 2. The sheet standard (every tab, same shape)

- **One tab per link type**, named **exactly** as above.
- **Row 1 = headers.** Data starts row 2.
- Columns (only **Source URL** is mandatory; the rest are optional and can be blank):

| Column header | Required | Meaning |
|---|:--:|---|
| **Source URL** | ✅ | The live page where the backlink appears. |
| **Target URL** | — | The URL we linked to. Leave blank to inherit the project's target. |
| **Anchor Text** | — | The anchor the link uses. |
| **Rel** | — | `dofollow` / `nofollow` / `sponsored` / `ugc`. |
| **Link Date** | — | Date the link went live. |
| **User** | — | Team member who built it (used for attribution & productivity). |
| **Notes** | — | Free-text comments. |

The **link type is the tab name** — there is no "link type" column. Header spelling
is flexible (the importer recognises synonyms like `Live Link`, `Backlink URL`,
`Placement Date`, `Assigned To`…), but the **tab name must be a canonical name**.

---

## 3. Rename cheat-sheet (old → canonical)

Rename each existing sub-sheet tab to the name on the right. Anything not listed
that isn't already canonical → pick the closest canonical name below.

| Current / messy name | → Canonical |
|---|---|
| Social Bookmarking · Social Bookamrking · SBM · Book Marking | **Social Bookmarking** |
| Web 2.0 · Web2.0 · Web 2.o | **Web 2.0** |
| Article · Article Submission · Article + Blog | **Article Submission** |
| Blog post | **Blog Post** |
| Guest Post · Guest Posting · Free Guest post · guest post old | **Guest Post** |
| Business Listings · Business Listing · Busniess Listing · Busniees Listing · Business Lisitng · listing · Web-Business Listings | **Business Listing** |
| Profile · Profile Submission · intern-profile | **Profile** |
| Profile & Forums · Forums & Profiles · Forum & Profiles · Profile + Forum · Profiles + Forums · forum discussion | **Profile & Forums** |
| Image Submission · Image Sub | **Image Submission** |
| PDF Submission · PDF | **PDF Submission** |
| Classified Ads posting · Classified Ads · classified | **Classified Ads** |
| Wiki Submission | **Wiki Submission** |
| Social Media · Socail Media | **Social Media** |
| Quora+PDF +Video · Quora+pinterest+reddit | **Q&A & Content Sharing** |
| GBP - Article Submission · GBP Article · GMB - Article Submission | **GBP – Article** |
| GBP - Web 2.0 · GBP Web 2.o · GMB Web 2.0 | **GBP – Web 2.0** |
| GBP - Citations · GBP-Citation | **GBP – Citation** |
| GMB Business Listings · GBP Business Listing | **GBP – Business Listing** |
| Google Maps Listing | **GBP – Maps** |
| Indexing Work · ZZTest* · ZZVerify* | *(not a link type — remove)* |

---

## 4. How to roll this out

1. **Hand the team the master template** (`docs/link-sentinel-master-sheet-template.xlsx`)
   — it already has one correctly-named tab per link type with the right headers.
2. **Clean the catalog** in the app: **Settings → Link types** → *merge* each messy
   name into its canonical name (dropdown), then *rename* stragglers. Merges keep
   all history. (This can also be scripted — see the maintenance runbook.)
3. **Rename old sheet tabs** to the canonical names using §3.
4. Tab-name **filtering** (only canonical tabs sync, others ignored) is **not enabled
   yet** — deferred by owner decision. All tabs still sync today; turning on the
   filter later will use exactly this canonical list.
