# Memory-safe held-out evaluation for the model-search loop (16 GB-friendly).
#
# Two OOM mechanisms hit this on a 16 GB Mac with the 104k-row frozen test set:
#   (1) log_lik(fit, newdata=test) materializes the 4000-draw x 104k-row matrix
#       in one shot (~3.3 GB just for the result, plus brms' internal predictor
#       matrices for splines + 3 REs — easily 8+ GB on top of a ~600 MB fit).
#       This is what killed the C0_nu4 eval AFTER convergence diagnostics
#       printed but BEFORE log_lik returned.
#   (2) posterior_predict on the full test set has the same shape.
# Fix: CHUNK BOTH steps. For each row-block, compute log_lik and accumulate the
# pointwise ELPD; then posterior_predict for mu / coverage. One block in memory
# at a time, never the full matrix.
suppressMessages({ library(brms); library(loo); library(dplyr); library(matrixStats) })

eval_and_log <- function(fit, candidate_id, train, test,
                         model_file = NULL, chunk = 4000) {
  if (!"date" %in% names(train)) train$date <- as.Date(train$service_date)

  n  <- nrow(test)
  blocks <- split(seq_len(n), ceiling(seq_len(n) / chunk))
  elpd_pw <- numeric(n)
  mu  <- numeric(n); cov <- logical(n)

  for (k in seq_along(blocks)) {
    ix <- blocks[[k]]
    nd <- test[ix, , drop = FALSE]

    # ── pointwise log_lik on this block only ──
    ll <- log_lik(fit, newdata = nd, allow_new_levels = TRUE,
                  sample_new_levels = "gaussian")
    # ELPD_i = log mean exp(log_lik[, i]) — done column-wise without forming new big mats
    elpd_pw[ix] <- matrixStats::colLogSumExps(ll) - log(nrow(ll))
    rm(ll); gc(verbose = FALSE)

    # ── posterior_predict on the same block for RMSE / 90% coverage ──
    pp <- posterior_predict(fit, newdata = nd, allow_new_levels = TRUE,
                            sample_new_levels = "gaussian")
    mu[ix] <- colMeans(pp)
    qs     <- matrixStats::colQuantiles(pp, probs = c(0.05, 0.95))
    cov[ix] <- test$delay_seconds[ix] >= qs[, 1] & test$delay_seconds[ix] <= qs[, 2]
    rm(pp, qs); gc(verbose = FALSE)

    if (k == 1 || k == length(blocks) || k %% 5 == 0)
      cat(sprintf("  [%s] eval block %d/%d (%d rows)\n", candidate_id, k, length(blocks), length(ix)))
  }

  saveRDS(elpd_pw, sprintf("../exports/elpd_pointwise_%s.rds", candidate_id))
  elpd_tot <- sum(elpd_pw); elpd_se <- sd(elpd_pw) * sqrt(length(elpd_pw))
  cat(sprintf("%s held-out ELPD=%.1f (SE %.1f) over %d rows\n",
              candidate_id, elpd_tot, elpd_se, length(elpd_pw)))
  base <- "../exports/elpd_pointwise_C0.rds"
  if (file.exists(base) && candidate_id != "C0") {
    pb <- readRDS(base)
    if (length(pb) == length(elpd_pw)) {
      d <- elpd_pw - pb
      cat(sprintf("  ΔELPD vs C0 = %.1f (SE %.1f)  [paired pointwise]\n",
                  sum(d), sd(d) * sqrt(length(d))))
    }
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
