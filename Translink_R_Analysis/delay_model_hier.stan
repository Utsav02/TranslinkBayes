
data {
  int<lower=0> N;
  vector[N] delay;
  vector[N] prev_delay;
  vector[N] distance;
  int<lower=1> hour[N];
  int<lower=1> dow[N];
  int<lower=1> trip[N];
  int<lower=1> N_trips;
  int<lower=1> max_hour;
  int<lower=1> max_dow;
}
parameters {
  real alpha;
  real beta_prev;
  real beta_dist;
  vector[max_hour] beta_hour;
  vector[max_dow] beta_dow;
  vector[N_trips] trip_effect;
  real<lower=0> sigma;
  real<lower=0> sigma_trip;
  real<lower=2> nu;
}
model {
  vector[N] mu;

  alpha ~ normal(0, 10);
  beta_prev ~ normal(0, 2);
  beta_dist ~ normal(0, 2);
  beta_hour ~ normal(0, 2);
  beta_dow ~ normal(0, 2);
  trip_effect ~ normal(0, sigma_trip);
  sigma ~ exponential(1);
  sigma_trip ~ exponential(1);
  nu ~ gamma(2, 0.1);

  for (n in 1:N) {
    mu[n] = alpha + beta_prev * prev_delay[n] + beta_dist * distance[n] +
            beta_hour[hour[n]] + beta_dow[dow[n]] + trip_effect[trip[n]];
  }
  delay ~ student_t(nu, mu, sigma);
}
generated quantities {
  vector[N] log_lik;
  vector[N] y_rep;
  for (i in 1:N) {
    real mu_i = alpha 
              + beta_prev * prev_delay[i]
              + beta_dist * distance[i]
              + beta_hour[hour[i]]
              + beta_dow[dow[i]]
              + trip_effect[trip[i]];
    log_lik[i] = student_t_lpdf(delay[i] | nu, mu_i, sigma);
    y_rep[i] = student_t_rng(nu, mu_i, sigma);
  }
}
