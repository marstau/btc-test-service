
def user_row_for_json(user):
    json = {
        'toshi_id': user['toshi_id'],
        'username': user['username'],
        'name': user['name'],
        'avatar': user['avatar'],
        'description': user['description'],
        'location': user['location']
    }
    if user['is_groupchatbot']:
        json['type'] = 'groupbot'
    elif user['is_bot']:
        json['type'] = 'bot'
    else:
        json['type'] = 'user'
    if not user['is_groupchatbot']:
        json['public'] = user['is_public']
        json['payment_address'] = user['payment_address']
        if user['reputation_score'] is not None:
            json['reputation_score'] = float(user['reputation_score'])
        else:
            json['reputation_score'] = 0
        if user['average_rating'] is not None:
            json['average_rating'] = float(user['average_rating'])
        else:
            json['average_rating'] = 0
        json['review_count'] = user['review_count']

    return json
