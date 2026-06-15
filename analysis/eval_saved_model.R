# Re-evaluate an ALREADY-FITTED candidate model on the frozen test set and append
# its run_log.csv row — no refit. Use when a fit succeeded but the eval crashed
# (e.g. the 16 GB OOM that lost C0_notrip's row), or to re-score a saved model.
#
#   Rscript eval_saved_model.R <CANDIDATE_ID>
# reads analysis/models/brms_<ID>.rds + the frozen loop_train/test parquets.
suppressMessages({ library(arrow); library(dplyr) })
source("loop_eval.R")

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("usage: Rscript eval_saved_model.R <CANDIDATE_ID>")
CID <- args[1]

prep <- function(p) arrow::read_parquet(p) |>
  mutate(trip_id = as.character(trip_id), stop_id = as.character(stop_id),
         route_id = as.character(route_id), hour = as.integer(hour), dow = as.integer(dow))
train <- prep("../exports/loop_train.parquet")
test  <- prep("../exports/loop_test.parquet")

model_path <- sprintf("models/brms_%s.rds", CID)
stopifnot(file.exists(model_path))
fit <- readRDS(model_path)
cat(sprintf("Re-evaluating saved %s on frozen test (%d rows), no refit\n", model_path, nrow(test)))

eval_and_log(fit, CID, train, test,
             model_file = sprintf("models/brms_%s.rds (%s re-eval %s, frozen test)",
                                  CID, CID, Sys.Date()))
cat("DONE — run_log.csv row appended.\n")
