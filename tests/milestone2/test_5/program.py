def slice_me():
    ages = [0, 25, 50, 75, 100]
    smallest_age = ages[0]
    middle_age = ages[2]
    highest_age = ages[-1]
    new_highest_age = middle_age + highest_age
    ages[-1] = 150 # slicing criterion
    return ages

slice_me()