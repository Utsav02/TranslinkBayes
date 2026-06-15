# Memory-safe held-out evaluation for the model-search loop (16 GB-friendly).
#
# The naive eval held a 4000-draw × 104k-test-row log_lik matrix AND a same-size
# posterior_predict matrix simultaneously (~3.3 GB each) → OOM on a 16 GB Mac.
# Fix: compute full-set ELPD via log_lik first, save only the small POINTWISE
# vector (for ΔELPD±SE), FREE the matrix, then get RMSE/coverage from a CHUNKED
# posterior_predict (one row-block in memory at a time).
suppressMessages({ library(brms); library(loo); library(dplyr) })

eval_and_log <- function(fit, candidate_id, train, test,
                         model_file = NULL, chunk = 8000) {
  if (!"date" %in% names(train)) train$date <- as.Date(train$service_date)

  # ── ELPD on the FULL test set (log_lik works at full size; free it after) ──
  ll <- log_lik(fit, newdata = test, allow_new_levels = TRUE,
                sample_new_levels = "gaussian")
  e       <- loo::elpd(ll)
  elpd_pw <- e$pointwise[, "elpd"]                       # length = nrow(test), tiny
  saveRDS(elpd_pw, sprintf("../exports/elpd_pointwise_%s.rds", candidate_id))
  cat(sprintf("%s held-out ELPD=%.1f (SE %.1f) over %d rows\n", candidate_id,
              e$estimates["elpd", "Estimate"], e$estimates["elpd", "SE"], length(elpd_pw)))
  base <- "../exports/elpd_pointwise_C0.rds"             # reference once C0 exists
  if (file.exists(base) && candidate_id != "C0") {
    pb <- readRDS(base)
    if (length(pb) == length(elpd_pw)) {
      d <- elpd_pw - pb
      cat(sprintf("  ΔELPD vs C0 = %.1f (SE %.1f)  [paired pointwise]\n",
                  sum(d), sd(d) * sqrt(length(d))))
    }
  }
  rm(ll); gc(verbose = FALSE)

  # ── RMSE / coverage from a CHUNKED posterior_predict ──────────────────────
  n <- nrow(test); mu <- numeric(n); cov <- logical(n)
  blocks <- split(seq_len(n), ceiling(seq_len(n) / chunk))
  for (ix in blocks) {
    pp <- posterior_predict(fit, newdata = test[ix, , drop = FALSE],
                            allow_new_levels = TRUE, sample_new_levels = "gaussian")
    mu[ix]  <- colMeans(pp)
    qs      <- apply(pp, 2, quantile, probs = c(0.05, 0.95))
    cov[ix] <- test$delay_seconds[ix] >= qs[1, ] & test$delay_seconds[ix] <= qs[2, ]
    rm(pp); gc(verbose = FALSE)
  }
  results <- test |> mutate(pred = mu, residual = delay_seconds - mu, covered = cov)
  cat(sprintf("%s MAE=%.2f RMSE=%.2f cov90=%.4f\n", candidate_id,
              mean(abs(results$residual)), sqrt(mean(results$residual^2)),
              mean(results$covered)))

  # ── Append the run_log row (loop memory) ──────────────────────────────────
  source("run_tracker.R")
  if (is.null(model_file))
    model_file <- sprintf("models/brms_%s.rds (loop %s, frozen test)", candidate_id, candidate_id)
  track_run(model = fit, train_df = train, test_df = test, results = results,
            model_file = model_file, n_routes = dplyr::n_distinct(train$route_id))
  invisible(results)
}
