# track_run() — append one row to exports/run_log.csv per model fit.
# Source this file, then call track_run() with explicit arguments.
#
# Usage (from inside an Rmd chunk, working dir = Translink_R_Analysis/):
#   source("run_tracker.R")
#   track_run(model = m2, train_df = train_df, test_df = test_df,
#             results = results, model_file = "models/brms_m2.rds")

track_run <- function(model, train_df, test_df, results,
                      model_file     = NA_character_,
                      n_routes       = NA_integer_) {
  out_path <- file.path("..", "exports", "run_log.csv")

  # ── Convergence diagnostics ──────────────────────────────────────────────
  # brms::rhat() and neff_ratio() are version-stable; avoids fragile smry$ access
  rhats     <- brms::rhat(model)
  rhat_max  <- max(rhats, na.rm = TRUE)

  n_post    <- (model$fit@sim$iter - model$fit@sim$warmup) * model$fit@sim$chains
  neff_rats <- brms::neff_ratio(model)
  ess_min   <- as.integer(floor(min(neff_rats, na.rm = TRUE) * n_post))

  np     <- bayesplot::nuts_params(model)
  n_divs <- sum(np$Value[np$Parameter == "divergent__"])

  # ── Key posteriors via posterior_summary() ────────────────────────────────
  # posterior_summary() uses brms internal names: b_previous_stop_delay, sigma,
  # nu, sd_route_id__Intercept. Returns a consistent numeric matrix.
  ps <- posterior_summary(model)

  b_prev_mean  <- as.numeric(ps["b_previous_stop_delay", "Estimate"])
  b_prev_q2.5  <- as.numeric(ps["b_previous_stop_delay", "Q2.5"])
  b_prev_q97.5 <- as.numeric(ps["b_previous_stop_delay", "Q97.5"])
  sigma_mean   <- as.numeric(ps["sigma", "Estimate"])
  nu_mean      <- as.numeric(ps["nu",    "Estimate"])

  # Route SD present only in M3
  route_sd_mean <- tryCatch(
    as.numeric(ps["sd_route_id__Intercept", "Estimate"]),
    error = function(e) NA_real_
  )

  # ── Holdout metrics ───────────────────────────────────────────────────────
  mae         <- mean(abs(results$residual))
  rmse        <- sqrt(mean(results$residual^2))
  coverage_90 <- mean(results$covered)

  # ── Build and append row ──────────────────────────────────────────────────
  row <- data.frame(
    run_date           = as.character(Sys.Date()),
    data_from          = as.character(min(train_df$date)),
    data_to            = as.character(max(train_df$date)),
    n_train            = nrow(train_df),
    n_test             = nrow(test_df),
    n_routes           = n_routes,
    b_prev_delay_mean  = round(b_prev_mean,  4),
    b_prev_delay_q2.5  = round(b_prev_q2.5,  4),
    b_prev_delay_q97.5 = round(b_prev_q97.5, 4),
    sigma_mean         = round(sigma_mean,    2),
    nu_mean            = round(nu_mean,       2),
    route_sd_mean      = round(route_sd_mean, 2),
    rhat_max           = round(rhat_max,      4),
    ess_min            = ess_min,
    n_divergences      = n_divs,
    mae                = round(mae,  2),
    rmse               = round(rmse, 2),
    coverage_90        = round(coverage_90, 4),
    model_file         = model_file,
    stringsAsFactors   = FALSE
  )

  if (file.exists(out_path)) {
    existing <- read.csv(out_path, stringsAsFactors = FALSE)
    combined <- rbind(existing, row)
  } else {
    combined <- row
  }

  write.csv(combined, out_path, row.names = FALSE)
  cat(sprintf("Run logged → %s  (total runs: %d)\n", out_path, nrow(combined)))
}
