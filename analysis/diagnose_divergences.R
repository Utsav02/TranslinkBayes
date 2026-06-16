# Divergence localization on an ALREADY-FITTED model (no refit). Mines the
# geometry of a saved brms fit to see WHERE divergent transitions cluster in
# hyperparameter space — the cheap way to decide which single experiment is
# worth the next multi-hour fit, instead of guessing.
#
#   Rscript diagnose_divergences.R <model_path> <label>
#
# For each hyperparameter (nu, sigma, the RE SDs) it compares the distribution
# on DIVERGENT vs NON-DIVERGENT post-warmup draws. A funnel shows up as
# divergences concentrating at SMALL values of an RE SD (on the log scale); a
# heavy-tail/likelihood problem shows up as divergences piling at the nu floor.
suppressMessages({ library(brms); library(posterior); library(bayesplot) })

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) stop("usage: Rscript diagnose_divergences.R <model_path> <label>")
mp <- args[1]; label <- args[2]
fit <- readRDS(mp)

# Hyperparameters of interest that actually exist in this model
want <- c("nu", "sigma",
          "sd_route_id__Intercept", "sd_stop_id__Intercept", "sd_trip_id__Intercept",
          "b_previous_stop_delay", "lp__")
have <- intersect(want, variables(fit))
dr <- as_draws_df(fit, variable = have)

# Divergence flag per post-warmup draw, aligned on (chain, iteration)
np  <- bayesplot::nuts_params(fit)
div <- np[np$Parameter == "divergent__", c("Chain", "Iteration", "Value")]
key_dr  <- paste(dr$.chain, dr$.iteration)
key_div <- paste(div$Chain, div$Iteration)
dr$div  <- div$Value[match(key_dr, key_div)]

ndiv <- sum(dr$div == 1, na.rm = TRUE); ntot <- nrow(dr)
cat(sprintf("\n===== %s =====\n", label))
cat(sprintf("post-warmup draws=%d  divergent=%d (%.1f%%)\n", ntot, ndiv, 100 * ndiv / ntot))
if (ndiv == 0) { cat("no divergences — nothing to localize\n"); quit(save = "no") }

cat(sprintf("\n%-26s %10s %10s %10s   %s\n", "parameter",
            "med|nondiv", "med|div", "shift", "where divergences sit"))
cat(strrep("-", 92), "\n")
for (v in setdiff(have, "lp__")) {
  x  <- dr[[v]]; d <- dr$div == 1
  mn <- median(x[!d], na.rm = TRUE); md <- median(x[d], na.rm = TRUE)
  # percentile of the divergent-draw median within the full marginal
  pctl <- mean(x <= md, na.rm = TRUE)
  note <- if (pctl < 0.25) "LOW tail  <-- funnel/boundary suspect" else
          if (pctl > 0.75) "HIGH tail <-- suspect" else "central (not localized)"
  cat(sprintf("%-26s %10.4f %10.4f %+9.4f   p%02.0f %s\n",
              v, mn, md, md - mn, 100 * pctl, note))
}

# nu specifically: how close to the lb=2 floor are divergent draws?
if ("nu" %in% have) {
  d <- dr$div == 1
  cat(sprintf("\nnu floor proximity: %.1f%% of divergent draws have nu<2.05 (vs %.1f%% of non-divergent)\n",
              100 * mean(dr$nu[d] < 2.05, na.rm = TRUE),
              100 * mean(dr$nu[!d] < 2.05, na.rm = TRUE)))
}
cat(sprintf("\n[%s done]\n", label))
