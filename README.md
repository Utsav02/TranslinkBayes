# **Bayesian Delay Propagation in Vancouver Bus Transit Network**

## **Project Overview**
Metro Vancouver’s bus transit system, operated by TransLink, is one of the finest in the continent. However, like all other transit systems around the globe, it experiences unpredictable delays due to congestion, weather, and operational inefficiencies. Through this project, I am trying to apply the concepts learned in the course and explore how Bayesian inference can be applied to model delay propagation in a high-frequency bus network of Vancouver using real-time GTFS data from TransLink. The objective is to develop a probabilistic framework for delay prediction while capturing uncertainty, leveraging historical data and hierarchical Bayesian modeling.

## **Project Theme**
My project is heavily influenced by a previous study conducted in Sweden taking a similar Bayesian approach (Rodriguez et al. (2022)).  Based on the project proposal themes, this project aligns with the theme of Bayesian regression and time series modeling. It can also be considered a spatial model since the dataset does have longitudes and latitudes, however, my current approach is not using it but I plan to try incorporating it by the project report.

## **Datasets & Data Collection**
I am using real-time and static GTFS datasets from TransLink. Static data comes from TransLink’s website (https://www.translink.ca/about-us/doing-business-with-translink/app-developer-resources/gtfs/gtfs-data) and the Real-time data is obtained by a Python script running on my local computer every 5 mins that stores the data in an SQLite database. The project structure is outlined in detail in the ReadMe file on the GitHub Repository. 


## **Project Methodology**

 The plan is to use hierarchical Bayesian regression to model stop-level delay propagation, leveraging a Student-t distribution as a prior to account for heavy-tailed transit delays (Rodriguez et al. (2022)). Using MCMC inference via RStan, I will estimate posterior delay parameters by incorporating previous stop delays to capture network-wide delay propagation. Optimistically, I also aim to explore spatial dependencies using latitude and longitude data from GTFS to refine the model. Lastly, another important goal is to develop a probabilistic delay prediction model that not only forecasts delay but also provides uncertainty estimates, offering transit agencies and commuters more interpretable and actionable insights. The question that still remains unanswered is if I wish to focus only on certain routes such as 99 or Rapid buses, or try to create a model for all buses which would be challenging since the basis of the model would be based on stops that are inherently different for each route. I plan to perform more EDA and explore this in order to have a concise final report that aligns with the project guidelines. 

## **Current Status**
✔️ **Data collection pipeline operational** (GTFS static + real-time data stored in SQLite).
✔️ **Exploratory Data Analysis (EDA) complete** (delay distributions, variance, skewness, and kurtosis per stop).
✔️ **Statistical validation of delay distributions underway** (Student-t vs Gaussian fit comparison).


## **Future Work**
- Implement hierarchical Bayesian regression with **RStan**.
- Investigate **spatial dependencies** using latitude/longitude data.
- Develop **a general stop-level model** that applies across multiple routes.
- Provide **a probabilistic delay prediction model** with uncertainty estimates.

## **References**
Rodriguez et al. (2022). *Robust Real-Time Delay Predictions in a Network of High-Frequency Urban Buses.*
