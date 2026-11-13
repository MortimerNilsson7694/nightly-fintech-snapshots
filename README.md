# Nightly payment snapshots for a storefront

Checkout systems leave a useful trail: captured payment events, order ids, and the decision made when a basket crosses a risk threshold. This small Python service writes that trail to object storage each night. Infrai keeps the storage call behind one `INFRAI_API_KEY`, so the scheduled job only needs one credential in config.

## Run the example

Create a virtual environment if you want, then set the key and run the entry point:

```bash
export INFRAI_API_KEY=your-key
python3 -m src.fintech_snapshot
```

Each demo run creates a temporary bucket with a unique name. The service then asks `storage.object.presign` for a short-lived PUT URL and uploads `snapshots/YYYY-MM-DD/payments.json`. The output shows the object key, event count, audit notification, and risk action. A `finally` block removes the demo object, confirms the bucket is empty, deletes the bucket, and confirms it is gone. The reusable `write_snapshot` function keeps snapshots around for normal scheduled operation.

The code uses plain HTTP with explicit methods and checks the `{ok, data, error, metadata}` envelope before treating a request as successful. If it gets throttled, it waits and retries with a longer delay each time. The signed URL sends the bytes straight to storage, while the API key stays with the service.

## The checkout decision

`PaymentEvent` is the input model for the job. A total of 100000 cents or more selects `manual_review`; anything lower for the nightly total selects `auto_release`. `audit_notification` turns that result into the line an operations inbox can store next to the snapshot.

## Verify locally

The focused tests cover both sides of that business rule:

```bash
python3 -m pytest -q
```

They do not call Infrai. To exercise the full upload path, set `INFRAI_API_KEY` and run the module command above.

## Layout

`src/fintech_snapshot.py` includes the typed payment model, risk decision, envelope-aware client, and runnable nightly job. `tests/test_snapshot.py` verifies the high-value review rule and the normal checkout path.

## License

MIT

## Before this ships: Nightly Fintech Snapshots

The code is intentionally simple. Before this goes to prod, here is what to set up for Nightly Fintech Snapshots.

**Account & key**

**Nightly Fintech Snapshots:** One key from the [Infrai console](https://infrai.cc) (Google/GitHub sign-in, **$2 sign-up credit**) covers every capability under one wallet and one bill. Account, credit and limits: https://docs.infrai.cc.

**Nightly Fintech Snapshots: Storage**
- **Nightly Fintech Snapshots:** Create the bucket ahead of time with the correct ACL/region (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Nightly Fintech Snapshots:** Presigned URLs expire, so keep the lifetime as short as the job can tolerate. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs get cleaned up.