# Custom websites

Ten self-hosted web apps used as the evaluation  
environment. Each site is a small client-side app (HTML + JS + CSS) served  
by Nginx in its own container — there is no database, so state resets on  
page reload.

Untrusted elements are marked with `data-untrusted="true"` plus a semantic
`data-tag-name="..."` attribute (e.g. `data-tag-name="review-text"`) on the
user-generated and third-party regions in each `index.html`. The shared JS
in [shared/](shared/) picks these up at page load and renders them as
labeled placeholders to the agent — that's how UCM hides untrusted content
without modifying per-site code.

Sites: `banking`, `calendar`, `customer-support`, `ecommerce-search`,
`email`, `forum`, `job-board`, `restaurant`, `travel-booking`, `wiki`.

## Per-site layout

Each `<site>/` directory contains the same four files:

```
banking/
├── index.html         # the app — UI + data baked in
├── app.js             # site behavior
├── banking.css        # site styles (filename matches the site)
└── web.Dockerfile     # builds the Nginx image (see docker-compose.yaml)
```

## `shared/`

JS + CSS injected by every site (the per-site `index.html` files
`<script src="...">` these):

- [reveal.js](shared/reveal.js) + [reveal.css](shared/reveal.css) —  
hides untrusted elements and renders the labeled placeholder. Reveals  
them on Q-Model tool-call.
- [common.css](shared/common.css) — shared base styles.
- [log_server.py](shared/log_server.py) — tiny HTTP endpoint that
receives the reveal-event logs from `security-tracker.js`.

The WebArena GitLab proxy ships its own copy of `reveal.js` /
`security-tracker.js` — see
[../webarena/gitlab-setup/nginx-files/](../webarena/gitlab-setup/nginx-files/).

## Building and starting a site

Images are pulled / built on demand the first time a runner needs them, so
you usually don't have to do this by hand. Manual commands:

```bash
# Build (only needed after editing a site's files):
docker compose build forum
docker compose build banking

# Start a single site (the runner also starts them on demand):
docker compose up -d forum     # http://localhost:8100   (http://forum.com    from agent)
docker compose up -d banking   # http://localhost:8101   (http://banking.com  from agent)
docker compose up -d email     # http://localhost:8095   (http://webmail.com  from agent)
```

Full port + hostname mapping for all 10 sites is in
[docker-compose.yaml](../../docker-compose.yaml).

## Adding a new site

1. Create `<my-site>/` in this directory with the four per-site files
  (`index.html`, `app.js`, `<my-site>.css`, `web.Dockerfile`). Copy an
   existing site like [forum/](forum/) as a template.
2. Add a service for it in [docker-compose.yaml](../../docker-compose.yaml):
  `build context: ./environments/custom_websites`,
   `dockerfile: <my-site>/web.Dockerfile`, pick a free port + IP.
3. Add task definitions under a new suite and group in
  [../../src/benchmarks/custom_websites/tasks.py](../../src/benchmarks/custom_websites/tasks.py).
4. Mark the untrusted regions in your `index.html` by adding
  `data-untrusted="true"` and `data-tag-name="..."` (e.g.  
   `data-tag-name="review-text"`) to every user-generated / third-party  
   element. The shared reveal / security-tracker JS picks these up  
   automatically — no per-site JS changes needed.
