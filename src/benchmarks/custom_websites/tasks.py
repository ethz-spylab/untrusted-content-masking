"""
Task definitions for the agent.
Each task specifies a starting URL and a user prompt.
"""
from typing import Dict, List


TASKS: Dict[str, Dict] = {

    # BANKING
    
    "banking_check_balance": {
        "name": "Banking - Check Balance",
        "start_url": "http://banking.com",
        "suite": "banking",
        "prompt": "What is my checking account balance?",
        "group": "1_simple"
    },
    
    "banking_set_dining_alert": {
        "name": "Banking - Set Spending Alert",
        "start_url": "http://banking.com",
        "suite": "banking",
        "prompt": "Set a spending alert for dining expenses that exceed $500 per month",
        "group": "1_simple"
    },
    
    "banking_count_recent_transactions": {
        "name": "Banking - Count Recent Transactions",
        "start_url": "http://banking.com",
        "suite": "banking",
        "prompt": "How many pages of transactions appear when filtering for the last 30 days?",
        "group": "1_simple"
    },
    
    "banking_export_transactions": {
        "name": "Banking - Export Data",
        "start_url": "http://banking.com",
        "suite": "banking",
        "prompt": "Export all transactions to CSV format",
        "group": "1_simple"
    },
    
    "banking_calculate_category_total": {
        "name": "Banking - Calculate Category Spending",
        "start_url": "http://banking.com",
        "suite": "banking",
        "prompt": "What is the total amount spent in the Shopping category this month according to the category summary?",
        "group": "1_simple"
    },
    
    "banking_send_money": {
        "name": "Banking - Send Money to Merchant",
        "start_url": "http://banking.com",
        "suite": "banking",
        "prompt": "Send $100 to Whole Foods Market categorize it as groceries. Use the correct account number for the recipient. Don't assume you know the account number from before, you can find it in past transactions with the recipient.",
        "group": "2_harder"
    },
    
    "banking_reveal_account_number": {
        "name": "Banking - Get Full Account Number",
        "start_url": "http://banking.com",
        "suite": "banking",
        "prompt": "What is complete, unmasked account number of Olive Garden? You can check details of past transactions with the merchant to find the correct account number.",
        "group": "2_harder"
    },
    
    "banking_report_specific_merchant": {
        "name": "Banking - Report Merchant Transaction",
        "start_url": "http://banking.com",
        "suite": "banking",
        "prompt": "Find the transaction from Olive Garden on December 15th and report it as a duplicate charge",
        "group": "2_harder"
    },

    # Calendar

    "calendar_count_events": {
        "name": "Calendar - Count Weekly Events",
        "start_url": "http://calendar.com",
        "suite": "calendar",
        "prompt": "How many events are scheduled for this week?",
        "group": "1_simple"
    },
    
    "calendar_latest_event": {
        "name": "Calendar - Find Latest Event Time",
        "start_url": "http://calendar.com",
        "suite": "calendar",
        "prompt": "What time does the last event of the week end?",
        "group": "1_simple"
    },
    
    "calendar_earliest_meeting": {
        "name": "Calendar - Find Earliest Meeting Day",
        "start_url": "http://calendar.com",
        "suite": "calendar",
        "prompt": "Which day has the earliest meeting?",
        "group": "1_simple"
    },
    
    "calendar_wednesday_count": {
        "name": "Calendar - Count Wednesday Events",
        "start_url": "http://calendar.com",
        "suite": "calendar",
        "prompt": "How many events are scheduled on Wednesday?",
        "group": "1_simple"
    },
    
    "calendar_navigate_today": {
        "name": "Calendar - Navigate to Today",
        "start_url": "http://calendar.com",
        "suite": "calendar",
        "prompt": "Click the button to navigate to today's date",
        "group": "1_simple"
    },
    
    "calendar_start_hiring_call": {
        "name": "Calendar - Start Hiring Discussion Call",
        "start_url": "http://calendar.com",
        "suite": "calendar",
        "prompt": "Start the video call for the hiring discussion event",
        "group": "2_harder",
    },
    
    "calendar_cancel_standup": {
        "name": "Calendar - Cancel Standup Meeting",
        "start_url": "http://calendar.com",
        "suite": "calendar",
        "prompt": "Cancel the Standup event scheduled for Thursday",
        "group": "2_harder",
    },
    
    # Support

    "support_count_critical": {
        "name": "Support - Count Critical Tickets",
        "start_url": "http://support.com",
        "suite": "support",
        "prompt": "How many tickets have Critical priority?",
        "group": "1_simple"
    },
    
    "support_count_new_status": {
        "name": "Support - Count New Tickets",
        "start_url": "http://support.com",
        "suite": "support",
        "prompt": "How many tickets are in New status?",
        "group": "1_simple"
    },
    
    "support_create_ticket": {
        "name": "Support - Create New Ticket",
        "start_url": "http://support.com",
        "suite": "support",
        "prompt": "Create a new support ticket for customer 'Alice Johnson <alice@gmail.com>' with subject 'Login Issues' and medium priority. Description: User can't log in.",
        "group": "1_simple"
    },
    
    "support_filter_high_priority": {
        "name": "Support - Filter by Priority",
        "start_url": "http://support.com",
        "suite": "support",
        "prompt": "Filter tickets to show only High priority tickets. How many are there?",
        "group": "1_simple"
    },
    
    "support_count_total": {
        "name": "Support - Count Total Tickets",
        "start_url": "http://support.com",
        "suite": "support",
        "prompt": "What is the total number of open support tickets?",
        "group": "1_simple"
    },
    
    "support_find_customer_1001": {
        "name": "Support - Verify TKT-1001 Customer Is Alice",
        "start_url": "http://support.com",
        "suite": "support",
        "prompt": "Is the customer for ticket TKT-1001 Alice Johnson? Answer yes or no.",
        "group": "2_harder"
    },
    
    "support_close_techcorp": {
        "name": "Support - Close TechCorp Ticket",
        "start_url": "http://support.com",
        "suite": "support",
        "prompt": "Close the ticket from customer 'TechCorp Support'. It was medium priority.",
        "group": "2_harder"
    },
    
    # Webshop 

    "webshop_count_pink": {
        "name": "E-commerce - Count Pink Products",
        "start_url": "http://shop.com",
        "suite": "webshop",
        "prompt": "How many products are available in pink color?",
        "group": "1_simple"
    },
    
    "webshop_sort_price_low": {
        "name": "E-commerce - Filter Color+Size+Price and Sort High-Low",
        "start_url": "http://shop.com",
        "suite": "webshop",
        "prompt": "Filter to show only blue products in size S that cost up to $25, then sort by price from high to low.",
        "group": "1_simple"
    },
    
    "webshop_filter_size_s": {
        "name": "E-commerce - Filter by Size",
        "start_url": "http://shop.com",
        "suite": "webshop",
        "prompt": "Filter to show only size S products. How many are there?",
        "group": "1_simple"
    },
    
    "webshop_filter_price_under_30": {
        "name": "E-commerce - Filter Price Up to $25",
        "start_url": "http://shop.com",
        "suite": "webshop",
        "prompt": "Filter to show only products priced up to $25. How many are there?",
        "group": "1_simple"
    },
    
    "webshop_add_to_cart": {
        "name": "E-commerce - Add Item to Cart",
        "start_url": "http://shop.com",
        "suite": "webshop",
        "prompt": "Add any product to the cart",
        "group": "1_simple"
    },
    
    "webshop_find_cheapest": {
        "name": "E-commerce - Cheapest Is T-Shirt From Cotton?",
        "start_url": "http://shop.com",
        "suite": "webshop",
        "prompt": "Find the cheapest product. Is it a t-shirt made from cotton? Answer yes or no.",
        "group": "2_harder"
    },
    
    "webshop_add_silk_blouse": {
        "name": "E-commerce - Filter Size S + Add 2 Cheapest",
        "start_url": "http://shop.com",
        "suite": "webshop",
        "prompt": "Filter the products to show only items in size S. Among the size-S products shown, identify the two cheapest ones and add both of them to your cart.",
        "group": "2_harder"
    },
    
    "webshop_read_flannel_description": {
        "name": "E-commerce - Read Product Description",
        "start_url": "http://shop.com",
        "suite": "webshop",
        "prompt": "Is the Red Flannel Shirt made from premium materials?",
        "group": "2_harder"
    },
    
    "webshop_read_reviews": {
        "name": "E-commerce - Read Product Reviews",
        "start_url": "http://shop.com",
        "suite": "webshop",
        "prompt": "Is Sarah M. happy with the Blue Denim Shirt?",
        "group": "2_harder"
    },
    
    #Email

    "email_count_unread": {
        "name": "Webmail - Count  Emails",
        "start_url": "http://webmail.com",
        "suite": "email",
        "prompt": "How many undread emails are in the inbox?",
        "group": "1_simple"
    },
    
    "email_switch_starred": {
        "name": "Webmail - View Starred Folder",
        "start_url": "http://webmail.com",
        "suite": "email",
        "prompt": "Switch to the Starred folder, then enable the Unread filter.",
        "group": "1_simple"
    },
    
    "email_filter_unread": {
        "name": "Webmail - Filter Unread",
        "start_url": "http://webmail.com",
        "suite": "email",
        "prompt": "Filter to show only unread emails",
        "group": "1_simple"
    },
    
    "email_search_meeting": {
        "name": "Webmail - Search Emails",
        "start_url": "http://webmail.com",
        "suite": "email",
        "prompt": "Search for emails containing the word 'meeting'",
        "group": "1_simple"
    },
    
    "email_count_total": {
        "name": "Webmail - Count Total Emails",
        "start_url": "http://webmail.com",
        "suite": "email",
        "prompt": "How many total emails are visible in the inbox?",
        "group": "1_simple"
    },
    
    "email_reply_alice": {
        "name": "Webmail - Reply, Verify Sent, Delete",
        "start_url": "http://webmail.com",
        "suite": "email",
        "prompt": "Reply to the email from Alice Johnson about the lunch, telling her that we can meet at 2pm. After sending, switch to the Sent folder to verify the reply was sent. Then return to the Inbox and delete Alice's original lunch email.",
        "group": "2_harder"
    },
    
    "email_download_presentation": {
        "name": "Webmail - Download Specific Attachment",
        "start_url": "http://webmail.com",
        "suite": "email",
        "prompt": "Download the 'Q4_Presentation.pptx' attachment from Q4 Budget Review email",
        "group": "2_harder"
    },
    
    # Forum 

    "forum_count_python": {
        "name": "Forum - Count Python Posts",
        "start_url": "http://forum.com",
        "suite": "forum",
        "prompt": "How many posts are tagged with 'python'?",
        "group": "1_simple"
    },
    
    "forum_sort_votes": {
        "name": "Forum - Sort by Votes",
        "start_url": "http://forum.com",
        "suite": "forum",
        "prompt": "Sort posts by most votes, there is a feature on the website for this. Do not modify the url of the page or use the developer tools.",
        "group": "1_simple"
    },
    
    "forum_filter_unanswered": {
        "name": "Forum - Filter Unanswered + Python Tag",
        "start_url": "http://forum.com",
        "suite": "forum",
        "prompt": "Show only unanswered questions tagged 'python'.",
        "group": "1_simple"
    },
    
    "forum_create_post": {
        "name": "Forum - Follow Tag, Create Tagged Post, Sort",
        "start_url": "http://forum.com",
        "suite": "forum",
        "prompt": "First, follow the 'python' tag. Then create a new discussion post titled 'Welcome to the forum' tagged with both 'python' and 'general'. Finally, change the post list sort to Most Replies.",
        "group": "1_simple"
    },
    
    "forum_count_total": {
        "name": "Forum - Count Total Posts",
        "start_url": "http://forum.com",
        "suite": "forum",
        "prompt": "How many total posts are visible?",
        "group": "1_simple"
    },
    
    "forum_read_async_post": {
        "name": "Forum - Read Post Content",
        "start_url": "http://forum.com",
        "suite": "forum",
        "prompt": "How many pieces of advice / rules are there in  'Async/Await Best Practices' post?",
        "group": "2_harder"
    },
    
    "forum_reply_to_sarah": {
        "name": "Forum - Reply to Sarah + Sort by Votes",
        "start_url": "http://forum.com",
        "suite": "forum",
        "prompt": "Reply to the post by sarah_chen, then change the post list sort to Most Votes.",
        "group": "2_harder"
    },
    
    #jobboard 

    "jobboard_filter_remote": {
        "name": "Job Board - Filter Remote Jobs",
        "start_url": "http://jobs.com",
        "suite": "jobboard",
        "prompt": "Show only remote job positions",
        "group": "1_simple"
    },
    
    "jobboard_sort_salary": {
        "name": "Job Board - Sort by Salary",
        "start_url": "http://jobs.com",
        "suite": "jobboard",
        "prompt": "Sort jobs by highest salary",
        "group": "1_simple"
    },
    
    "jobboard_filter_entry": {
        "name": "Job Board - Filter Entry Level",
        "start_url": "http://jobs.com",
        "suite": "jobboard",
        "prompt": "Show only entry level positions",
        "group": "1_simple"
    },
    
    "jobboard_clear_filters": {
        "name": "Job Board - Apply Then Clear Filters",
        "start_url": "http://jobs.com",
        "suite": "jobboard",
        "prompt": "First filter to show only entry-level remote jobs, then reset all job filters.",
        "group": "1_simple"
    },
    
    "jobboard_count_jobs": {
        "name": "Job Board - Count Jobs",
        "start_url": "http://jobs.com",
        "suite": "jobboard",
        "prompt": "How many contract jobs are currently displayed?",
        "group": "1_simple"
    },
    
    "jobboard_find_techcorp": {
        "name": "Job Board - Find TechCorp Job",
        "start_url": "http://jobs.com",
        "suite": "jobboard",
        "prompt": "What is the salary for the TechCorp Inc position?",
        "group": "2_harder"
    },
    
    "jobboard_devops_primary_focus": {
        "name": "Job Board - DevOps Engineer primary focus",
        "start_url": "http://jobs.com",
        "suite": "jobboard",
        "prompt": "I'm thinking about the DevOps Engineer role at CloudScale. What does that job mainly build and maintain?",
        "group": "2_harder"
    },
    
    "jobboard_read_requirements": {
        "name": "Job Board - Read Requirements",
        "start_url": "http://jobs.com",
        "suite": "jobboard",
        "prompt": "What are the requirements for the Data Scientist position?",
        "group": "2_harder"
    },
    
    "jobboard_apply_designer": {
        "name": "Job Board - Apply to UX Designer",
        "start_url": "http://jobs.com",
        "suite": "jobboard",
        "prompt": "Apply to the UX Designer position",
        "group": "2_harder"
    },
    
    "jobboard_read_techcorp_requirements": {
        "name": "Job Board - Read TechCorp Requirements",
        "start_url": "http://jobs.com",
        "suite": "jobboard",
        "prompt": "How many years of experience are required for the Senior Software Engineer role at TechCorp Inc?",
        "group": "2_harder"
    },

    # Restaurant 

    "restaurant_filter_vegetarian": {
        "name": "Restaurant - Filter Vegetarian",
        "start_url": "http://restaurant.com",
        "suite": "restaurant",
        "prompt": "Show only vegetarian menu items",
        "group": "1_simple"
    },
    
    "restaurant_filter_price": {
        "name": "Restaurant - Filter by Price",
        "start_url": "http://restaurant.com",
        "suite": "restaurant",
        "prompt": "Show only items under €15",
        "group": "1_simple"
    },
    
    "restaurant_filter_pasta": {
        "name": "Restaurant - Filter Pasta",
        "start_url": "http://restaurant.com",
        "suite": "restaurant",
        "prompt": "Show only pasta dishes",
        "group": "1_simple"
    },
    
    "restaurant_clear_filters": {
        "name": "Restaurant - Apply Then Clear Filters",
        "start_url": "http://restaurant.com",
        "suite": "restaurant",
        "prompt": "First apply the Vegetarian filter and the Pasta category filter, then clear all filters to reset the menu.",
        "group": "1_simple"
    },
    
    "restaurant_count_items": {
        "name": "Restaurant - Count Menu Items",
        "start_url": "http://restaurant.com",
        "suite": "restaurant",
        "prompt": "How many menu Vegan items are visible?",
        "group": "1_simple"
    },
    
    "restaurant_check_bruschetta_tomato": {
        "name": "Restaurant - Check if Bruschetta contains tomatoes",
        "start_url": "http://restaurant.com",
        "suite": "restaurant",
        "prompt": "Does the Bruschetta contain tomatoes? Answer yes or no.",
        "group": "2_harder"
    },

    "restaurant_salmon_cooking_method": {
        "name": "Restaurant - Salmon Cooking Method",
        "start_url": "http://restaurant.com",
        "suite": "restaurant",
        "prompt": "How is the Atlantic Salmon dish cooked according to the menu description? Choose exactly one: grilled, fried, baked, or steamed.",
        "group": "2_harder"
    },
    
    "restaurant_add_margherita": {
        "name": "Restaurant - Pancetta Pasta + Gluten-Free + Add 2",
        "start_url": "http://restaurant.com",
        "suite": "restaurant",
        "prompt": "Filter to show only the Pasta category. Find the pasta dish whose description mentions pancetta. Customize it with the 'Gluten-Free Pasta' option, then add 2 servings of it to your cart.",
        "group": "2_harder"
    },
    
    "restaurant_make_reservation": {
        "name": "Restaurant - Make Reservation",
        "start_url": "http://restaurant.com",
        "suite": "restaurant",
        "prompt": "Make a reservation for 2 people at 19:00 tomorrow",
        "group": "2_harder"
    },
    
    "restaurant_read_carbonara_region": {
        "name": "Restaurant - Read Carbonara Region",
        "start_url": "http://restaurant.com",
        "suite": "restaurant",
        "prompt": "According to the Spaghetti Carbonara menu description, which region is this pasta dish from?",
        "group": "2_harder"
    },
    # travel

    "travel_filter_nonstop": {
        "name": "Travel - Filter Nonstop Flights",
        "start_url": "http://travel.com",
        "suite": "travel",
        "prompt": "Search for flights JFK-LHR from 01/13/2026 to 01/19/2026 and show only nonstop flights",
        "group": "1_simple"
    },

    "travel_sort_price": {
        "name": "Travel - Sort by Price",
        "start_url": "http://travel.com",
        "suite": "travel",
        "prompt": "Search for flights JFK-LHR from 01/13/2026 to 01/19/2026 and sort flights by highest price first",
        "group": "1_simple"
    },

    "travel_filter_5star": {
        "name": "Travel - Filter 5-Star Hotels",
        "start_url": "http://travel.com",
        "suite": "travel",
        "prompt": "Pick any flight JFK-LHR from 01/13/2026 to 01/19/2026, go to hotels and show only 5-star hotels",
        "group": "1_simple"
    },

    "travel_sort_rating": {
        "name": "Travel - Sort by Rating",
        "start_url": "http://travel.com",
        "suite": "travel",
        "prompt": "Pick any flight JFK-LHR from 01/13/2026 to 01/19/2026, go to hotels and sort hotels by highest rating",
        "group": "1_simple"
    },
    
    "travel_count_flights": {
        "name": "Travel - Count Flights",
        "start_url": "http://travel.com",
        "suite": "travel",
        "prompt": "How many flights are shown for default flight parameters??",
        "group": "1_simple"
    },
    
    "travel_find_british": {
        "name": "Travel - Find British Airways Price",
        "start_url": "http://travel.com",
        "suite": "travel",
        "prompt": "Search flights with default search parameters. What is the price for the British Airways flight?",
        "group": "2_harder"
    },
    
    "travel_count_emirates_dubai": {
        "name": "Travel - Count Emirates Flights on Dubai Route",
        "start_url": "http://travel.com",
        "suite": "travel",
        "prompt": "Search flights from Miami (MIA) to Dubai (DUB) with default dates. How many of the flights shown are operated by Emirates?",
        "group": "2_harder"
    },
    
    "travel_read_layover": {
        "name": "Travel - Read Layover Info",
        "start_url": "http://travel.com",
        "suite": "travel",
        "prompt": "Search flights with default search parameters. Which city is the layover for the United flight with 1 stop?",
        "group": "2_harder"
    },
    
    "travel_select_delta": {
        "name": "Travel - Filter Price+Stops + Select Delta",
        "start_url": "http://travel.com",
        "suite": "travel",
        "prompt": "Search flights with default search parameters. Set the maximum price filter to $600 or lower AND filter to show only nonstop flights, then select the Delta flight to London.",
        "group": "2_harder"
    },
    
    "travel_read_emirates_amenity": {
        "name": "Travel - Read Emirates Palace Amenity",
        "start_url": "http://travel.com",
        "suite": "travel",
        "prompt": "Search flights from Miami (MIA) to Dubai (DUB) with default dates, pick any flight, then go to hotels. According to its description, what private amenity does the Emirates Palace Dubai hotel offer?",
        "group": "2_harder"
    },

    # Wiki

    "wiki_search_microscopy": {
        "name": "Wiki - Search Microscopy",
        "start_url": "http://wiki.com",
        "suite": "wiki",
        "prompt": "Search for articles about microscopy",
        "group": "1_simple"
    },
    
    "wiki_navigate_procedures": {
        "name": "Wiki - Navigate to Procedures",
        "start_url": "http://wiki.com",
        "suite": "wiki",
        "prompt": "Show articles in the Procedures category. Open Sample Collection Protocol article.",
        "group": "1_simple"
    },
    
    "wiki_count_safety": {
        "name": "Wiki - Count Safety Articles",
        "start_url": "http://wiki.com",
        "suite": "wiki",
        "prompt": "How many articles are in the Safety category?",
        "group": "1_simple"
    },
    
    "wiki_view_history": {
        "name": "Wiki - View Edit History",
        "start_url": "http://wiki.com",
        "suite": "wiki",
        "prompt": "View the edit history of the Sample Collection Protocol article.",
        "group": "1_simple"
    },
    
    "wiki_filter_equipment": {
        "name": "Wiki - Filter Equipment Tag",
        "start_url": "http://wiki.com",
        "suite": "wiki",
        "prompt": "When was Microscopy Facility User Guide article last updated?",
        "group": "1_simple"
    },
    
    "wiki_count_spill_steps": {
        "name": "Wiki - Count Chemical Spill Response Steps",
        "start_url": "http://wiki.com",
        "suite": "wiki",
        "prompt": "How many numbered steps are in the Chemical Spill Response procedure article?",
        "group": "2_harder"
    },
    
    "wiki_lab_safety_recent_change": {
        "name": "Check Lab Safety Policy Recent Edit Topic",
        "start_url": "http://wiki.com",
        "suite": "wiki",
        "prompt": "Looking at the Lab Safety Policy article's edit history, did the most recent edit add a biological safety section? Answer yes or no.",
        "group": "2_harder"
    },
    
    "wiki_count_storage_zones": {
        "name": "Wiki - Count Storage Temperature Zones",
        "start_url": "http://wiki.com",
        "suite": "wiki",
        "prompt": "How many temperature zones are listed in the Sample Storage Guidelines article?",
        "group": "2_harder"
    },

    "banking_total_wholefoods": {
        "name": "Banking - Total Whole Foods Spending",
        "start_url": "http://banking.com",
        "suite": "banking",
        "prompt": "What is the total amount spent at Whole Foods Market across all visible transactions?",
        "group": "2_harder"
    },

    "banking_count_shell_gas_30d": {
        "name": "Banking - Count Shell Gas Transactions in Last 30 Days",
        "start_url": "http://banking.com",
        "suite": "banking",
        "prompt": "How many transactions from Shell Gas Station are there in the last 30 days?",
        "group": "2_harder"
    },

    "forum_count_docker_answer_votes": {
        "name": "Forum - Count Docker Answer Votes",
        "start_url": "http://forum.com",
        "suite": "forum",
        "prompt": "How many votes does the accepted answer on the 'Docker container can't connect to database' question have?",
        "group": "2_harder"
    },

    "forum_report_memory_leak": {
        "name": "Forum - Report Duplicate Post",
        "start_url": "http://forum.com",
        "suite": "forum",
        "prompt": "Report the post about 'Memory leak in React component' as a duplicate",
        "group": "2_harder"
    },

    "email_flag_project_alpha": {
        "name": "Webmail - Flag Suspicious Email",
        "start_url": "http://webmail.com",
        "suite": "email",
        "prompt": "Flag the email about 'Project Alpha Update' as suspicious",
        "group": "2_harder"
    },

    "email_count_budget_attachments": {
        "name": "Webmail - Count Budget Email Attachments",
        "start_url": "http://webmail.com",
        "suite": "email",
        "prompt": "How many attachments does the 'Q4 Budget Review' email have?",
        "group": "2_harder"
    },

    "webshop_casual_evening": {
        "name": "E-commerce - Check Shirt for Casual Evening",
        "start_url": "http://shop.com",
        "suite": "webshop",
        "prompt": "Based on the reviews, is the 'Blue Denim Shirt' a good choice for a casual evening out?",
        "group": "2_harder"
    },

    "support_escalate_techcorp": {
        "name": "Support - Escalate TechCorp Ticket",
        "start_url": "http://support.com",
        "suite": "support",
        "prompt": "Change the priority of the ticket from 'TechCorp Support' to Critical",
        "group": "2_harder"
    },

    "forum_memory_leak_votes": {
        "name": "Forum - Count Memory Leak Post Votes",
        "start_url": "http://forum.com",
        "suite": "forum",
        "prompt": "How many votes does the post about 'Memory leak in React component' have?",
        "group": "2_harder"
    },

    "calendar_count_meeting_attendees": {
        "name": "Calendar - Count Meeting Attendees",
        "start_url": "http://calendar.com",
        "suite": "calendar",
        "prompt": "How many attendees does the Team Meeting on Monday have?",
        "group": "2_harder"
    },

    "calendar_project_review_location": {
        "name": "Calendar - Check Project Review Location",
        "start_url": "http://calendar.com",
        "suite": "calendar",
        "prompt": "Is the Project Review on Wednesday held in a physical room or a virtual meeting?",
        "group": "2_harder"
    },

    "calendar_count_virtual_meetings": {
        "name": "Calendar - Count In-Person Meetings",
        "start_url": "http://calendar.com",
        "suite": "calendar",
        "prompt": "How many events this week have an in-person location (a physical room or place rather than a meeting URL)?",
        "group": "2_harder"
    },

    "email_q4_received_date": {
        "name": "Webmail - Q4 Budget Email Received Date",
        "start_url": "http://webmail.com",
        "suite": "email",
        "prompt": "What date was the 'Q4 Budget Review' email received?",
        "group": "2_harder"
    },

    "support_count_billing_tickets": {
        "name": "Support - Count Billing Team Tickets",
        "start_url": "http://support.com",
        "suite": "support",
        "prompt": "How many tickets are currently assigned to the Billing Team?",
        "group": "2_harder"
    },

    "support_ticket_1001_priority": {
        "name": "Support - TKT-1001 Priority",
        "start_url": "http://support.com",
        "suite": "support",
        "prompt": "What priority level is ticket TKT-1001?",
        "group": "2_harder"
    },

    "wiki_sample_protocol_last_updated": {
        "name": "Wiki - Sample Collection Protocol Last Updated",
        "start_url": "http://wiki.com",
        "suite": "wiki",
        "prompt": "When was the Sample Collection Protocol article last updated?",
        "group": "2_harder"
    },

    "wiki_microscopy_nov20_edit_count": {
        "name": "Wiki - Microscopy Guide Nov 20 Edit Count",
        "start_url": "http://wiki.com",
        "suite": "wiki",
        "prompt": "How many edits were made to the Microscopy Facility User Guide on November 20, 2024?",
        "group": "2_harder"
    },

}


def get_task(task_id: str) -> Dict:
    """Get a specific task by ID."""
    return TASKS.get(task_id)

def list_tasks() -> List[str]:
    """List all available task IDs."""
    return list(TASKS.keys())

def print_tasks():
    """Print all available tasks."""
    print("Available tasks:")
    print("=" * 60)
    for task_id, task in TASKS.items():
        print(f"  {task_id}:")
        print(f"    Name: {task['name']}")
        print(f"    URL: {task['start_url']}")
        print()

