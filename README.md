##Project overview

This is an effort to use data science and statistics to determine who is the best fantasy football manager across time.  To begin with, this is mostly bespoke to a specific league of ~10 managers, but I have aspirations to be able to apply this to any Yahoo fantasy football league and provide results.

This works by taking league result data from Yahoo: The obvious stuff like teams, win/loss rate, final season rank, points scored.  But it also gathers data about individual player performances, manager draft efficiency, in-season pickups, FAAB spending efficiency.  We frequently use a calculated feature to represent a manager's success on a particular dimension of fantasy football.  And these individual dimensions/metrics are each given a weight.  For example, "points scored" may be given a weight of 40, indicating that a manager may score up to 40 on that dimension.  Taking all metrics together gives a "composite rank", and we can stack managers against each other on this basis.  

Data is collected manually and through Selenium webscrapers.  All code is, as of writing, written in python and executed within a jupyter notebook.  A Google colab notebook is used to share the final compiled results with stakeholders.  

There is some maintenance required each year to ensure that web scrapers are still working, as well as the manual data collection.  There is also manual data cleanup, especially relating to player data.  

##Instructions notes

Steps:

1. sraping_yahoo_testing.ipynb -> consolidated_master.csv, all_regular_season_thru_[YEAR].csv, all_playoffs_thru_[YEAR].csv
1. NOTE - due to many manual changes, it's recommended that you take the new year only and append to previous year's consolidated master
1. Add season column to the playoffs df (update code to do this)
1. player_data_nb.ipynb -> position_ranks_thru_[YEAR].csv - this sheet also seems to be where we've made attempts to reconcile player lkup issues
1. faab_offers.ipynb -> faab_thru_[YEAR].csv
1. add draft, faab players to lkup_player, names_dict
1. make sure seasons is in consolidated master
1. deal with any spelling inconsistencies between draft, lkup_player, names_dict
1. btw Mike Williams, there's really only two that are relevant
1. draft_data_compiler -> full_seasons_draft_df.csv
1. add "is_drafted" to rs_thru_[YEAR]
1. Ensure manager names are standardized (check draft esepcially)
1. Ensure that revised_p_score is retained to include manual fixes for 2020 and 2022
1. Ensure manager attribute is included in conslidated master
1. Make sure Scott isn't in twice in 2010 due to co-manager status for Luke's account, Oober Gey
1. Make sure manual edits to playoff points are retained
1. There's an issue with matching on manager team name because of special characters for example Ruggsâ€™ Getaway Car