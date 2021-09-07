import io
import json
import boto3
import os
import pandas as pd
from fuzzywuzzy import process


import time, random
from urllib import request



def questionify(lines):
    # with open('text.txt', 'r') as file:
    lines = lines

    drop_str = ['ATTEMPT ALL QUESTIONS IN BRIEF.', 'ATTEMPT ANY THREE OF THE FOLLOWING:',
                'ATTEMPT ANY ONE PART OF THE FOLLOWING:',
                'ATTEMPT ALL QUESTIONS IN BRIEF:', 'ATTEMPT ANY THREE OF THE FOLLOWING.',
                'ATTEMPT ANY ONE PART OF THE FOLLOWING.',
                'ATTEMPT ALL QUESTIONS IN BRIEF', 'ATTEMPT ANY THREE OF THE FOLLOWING',
                'ATTEMPT ANY ONE PART OF THE FOLLOWING']
    words = ['MARKS', 'CO', 'QUESTION', 'NOTE', 'QNO.', 'QNO']
    question_end = ['.', '?', ',', '!']
    lines1 = []

    qa, qb, qc, question = [], [], [], ''
    section_a, section_b, section_c, q_line_start, q_line_end = 0, 0, 0, 0, 0
    lines_in_q = True

    # lines = file.readlines()
    for line in lines:
        line = line.split('\n')[0].upper()
        if not len(line) < 5:
            lines1.append(line)

    for w in words: drop_str.append(w)

    lines = []
    for x in (line for line in lines1 if line not in drop_str):
        lines.append(x)

    for i, line in enumerate(lines):
        if line == 'SECTION A': section_a, section_b, section_c = 1, 0, 0
        if line == 'SECTION B': section_a, section_b, section_c = 0, 1, 0
        if line == 'SECTION C': section_a, section_b, section_c = 0, 0, 1

        for qe in question_end:
            if line.endswith(qe):
                if lines_in_q: q_line_start = i
                q_line_end = i

                question = lines[q_line_start + 1]
                if q_line_start < q_line_end:
                    for q in range(q_line_end - q_line_start - 1):
                        q_line_start += 1
                        question += ' ' + lines[q_line_start + 1]

                if section_a: qa.append(question)
                if section_b: qb.append(question)
                if section_c: qc.append(question)

                question = ''
                lines_in_q = True
            else:
                if lines_in_q:
                    q_line_start = i
                    lines_in_q = False

    #     print(QA)  # miss the first question on every section.
    #     print(QB)
    #     print(QC)  # for section-c question, leave the first question if answer is not matching.
    return qa, qb, qc


def lambda_handler(event, context):
    photoUrl, s3_files_for_use, lines = [], [], []  # "Get it from the API execution"

    # 1. parse out query string parameters

    for i in range(10):
        try:
            if event['queryStringParameters']['photoUrl_' + str(i)] is not None:
                photoUrl.append(event['queryStringParameters']['photoUrl_' + str(i)])
        except Exception as e:
            continue

    sem_plus_sub = event['queryStringParameters']['sem_plus_sub']  # no capital, no underscore

    region = 'us-west-2'
    bucket_name = sem_plus_sub + '-textract-upload'
    csv_file_name = sem_plus_sub + '.csv'
    lambda_tmp_path = '/tmp'

    # amazon textract
    textract = boto3.client(service_name='textract', region_name=region)
    # amazon s3
    s3 = boto3.client('s3')

    def dl_img_upload_to_s3(url):
        random.seed(time.time())
        file_name = 'photo' + str(random.random()) + '.jpg'
        s3_files_for_use.append(file_name)
        full_path = os.path.join(lambda_tmp_path, file_name)
        # downloading file from firebase and uploading to s3
        request.urlretrieve(url=url, filename=full_path)
        s3.upload_file(Filename=full_path, Bucket=bucket_name, Key=file_name)

    # Downloading all the images and uploading to the s3
    for url in photoUrl:
        dl_img_upload_to_s3(url)

    del photoUrl, url

    for s3_file in s3_files_for_use:
        try:
            response = textract.detect_document_text(
                Document={
                    "S3Object": {
                        "Bucket": bucket_name,
                        "Name": s3_file}})

            for item in response["Blocks"]:
                if item["BlockType"] == "LINE":
                    lines.append(item["Text"])
        except Exception as e:
            print(e)

    qa, qb, qc = questionify(lines)

    del lines, s3_files_for_use, textract, response

    ################################ reading csv_file
    csv_file = s3.get_object(Bucket=bucket_name, Key=csv_file_name)  # csv_file_obj
    csv_file = csv_file['Body'].read()  # csv_file_bytes
    csv_file = io.BytesIO(csv_file)  # csv_bytes_to_file

    df = pd.read_csv(csv_file)

    del csv_file

    ################################ beginning question answer formatting

    n_char_in_A_ans = 250
    n_char_in_B_ans = 1250
    n_char_in_C_ans = 1250

    Question1_list = list(df['Question1'])
    Question2_list = list(df['Question2'])

    A_ans, B_ans, C_ans = [], [], []
    best, best1, best2 = [], [], []

    ############################### section-A question answer formatting
    for i, que in enumerate(qa):
        best1.append(process.extractOne(que, Question1_list))
        best2.append(process.extractOne(que, Question2_list))

        if best1[i][1] > best2[i][1]:
            for j, que in enumerate(Question1_list):
                if que == best1[i][0]:
                    A_ans.append([que, str(df.at[j, 'Answer'])[:n_char_in_A_ans]])
                    break
        else:
            for j, que in enumerate(Question2_list):
                if que == best2[i][0]:
                    A_ans.append([que, str(df.at[j, 'Answer'])[:n_char_in_A_ans]])
                    break
    del qa, n_char_in_A_ans
    ################################ section-B question answer formatting

    best, best1, best2 = [], [], []
    best1_similar, best2_similar = [], []

    for i, que in enumerate(qb):
        best1.append(process.extractOne(que, Question1_list))
        best2.append(process.extractOne(que, Question2_list))

        if best1[i][1] > best2[i][1]:
            best1_similar.append(best1[i])
        else:
            best2_similar.append(best2[i])

    del qb
    best1, best2 = [], []

    for best2_s in best2_similar: best1_similar.append(best2_s)

    ############ sorting the questions in descending form of duplication
    for i in range(len(best1_similar)):
        min_idx = 1
        for j in range(i + 1, len(best1_similar)):
            if best1_similar[min_idx][1] < best1_similar[j][1]:
                min_idx = j
        best1_similar[i], best1_similar[min_idx] = best1_similar[min_idx], best1_similar[i]

    for i, best1_s in enumerate(best1_similar):
        if i > 2: break
        found = 0
        for j, que in enumerate(Question1_list):
            if que == best1_s:
                B_ans.append([best1_s[0], str(df.at[j, 'Answer'])[:n_char_in_B_ans]])
                found = 1
                break
            if found != 1:
                for j, que in enumerate(Question2_list):
                    if que == best1_s:
                        B_ans.append([best1_s[0], str(df.at[j, 'Answer'])[:n_char_in_B_ans]])
                        break

    del best1_s, n_char_in_B_ans

    ######################## section-C question answer formatting
    best, best1_1, best2_2 = [], [], []
    best_similar, best1_similar, best2_similar = [], [], []

    for i, que in enumerate(qc):
        if i % 2 == 0:
            best1.append(process.extractOne(que, Question1_list))
            best2.append(process.extractOne(que, Question2_list))
            continue
        if i % 2 != 0:
            best1_1.append(process.extractOne(que, Question1_list))
            best2_2.append(process.extractOne(que, Question2_list))
            try:
                if best1[i - 1][1] > best2[i - 1][1]:
                    best1_similar.append(best1[i - 1])
                else:
                    best2_similar.append(best2[i - 1])
            except IndexError:pass
            try:
                if best1_1[i][1] > best2_2[i][1]:
                    best2_similar.append(best1_1[i])
                else:
                    best2_similar.append(best2_2[i])
            except IndexError: pass
            try:
                if best1_similar[i - 1][1] > best2_similar[i][1]:
                    best_similar.append(best1_similar[i - 1])
                else:
                    best_similar.append(best2_similar[i])
            except IndexError:pass
    # garbage collection
    del best1_similar, best2_similar, best, best1, best2, best1_1, best2_2

    for i, best_s in enumerate(best_similar):
        found = 0
        for j, que in enumerate(Question1_list):
            if que == best_s:
                C_ans.append([best_s[0], str(df.at[j, 'Answer'])[:n_char_in_C_ans]])
                found = 1
                break
        if found != 1:
            for j, que in enumerate(Question2_list):
                if que == best_s:
                    C_ans.append([best_s[0], str(df.at[j, 'Answer'])[:n_char_in_C_ans]])
                    break

    # garbage collection
    del best_similar, df, que, Question1_list, Question2_list, n_char_in_C_ans

    output_file_txt = lambda_tmp_path + '/' + sem_plus_sub + '-question-plus-answer.txt'
    key_output = sem_plus_sub + '-question-plus-answer.txt'
    ans_1, ans_2, ans_3 = "", "", ""

    with open(output_file_txt, 'w') as f:
        for i in A_ans:
            temp = 'Section A Question                    ' + i[0] + ' Answer.                     ' + i[
                1] + '                    '
            f.write(temp)
            ans_1 += temp
        del A_ans
        for i in B_ans:
            temp = 'Section B Question                    ' + i[0] + ' Answer.                     ' + i[
                1] + '                    '
            f.write(temp)
            ans_2 += temp
        del B_ans
        for i in C_ans:
            temp = 'Section C Question                    ' + i[0] + ' Answer.                     ' + i[
                1] + '                    '
            f.write(temp)
            ans_3 += temp
        del C_ans

    # uploading output file to s3
    s3.upload_file(Filename=output_file_txt, Bucket=bucket_name, Key=key_output)

    # url = 'https://' + bucket_name + '.s3-' + region + ".amazonaws.com/" + key_output

    #2. Consrtuct the body of response object
    response = {}
    response['1_ans'] = ans_1
    response['2_ans'] = ans_2
    response['3_ans'] = ans_3
    del ans_1, ans_2, ans_3

    #3. Construct http request object
    responseObject = {}
    responseObject['statusCode'] = 200
    responseObject['headers'] = {}
    responseObject['headers']['content-type'] = 'application/json'
    responseObject['body'] = json.dumps(response)


    # 4 return the response object
    return responseObject


