# Insights dashboard

The page at `/insights/` on the site distribution. React, TypeScript and Vite, with charts from the Bklit UI registry (copied into `src/components/charts`).

The page reads `data.json` from its own folder. The pipeline's publish step writes that file after each daily run, so it is never part of this build.

```
npm ci
npm run dev     # uses src/dev/data.sample.json, which is not committed
npm run build   # type-checks, then writes dist/
```

Terraform uploads `dist/` to `insights/` in the site bucket, so build before `terraform apply`.
