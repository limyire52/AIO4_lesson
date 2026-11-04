import streamlit as st

st.title('ui 실습')
st.caption('입력->공백 검사->대화내용 미리보기')
name = st.text_input('이름',placeholder="예시) 민수")
question = st.text_input('질문',placeholder="streamlit은 무엇인가요?")

show_hint = st.checkbox('실행원리 설명 보기')
if show_hint:
    st.info('입력 값을 확정하거나, 버튼을 누르면 ~~ 실행됩니다.') # 한줄로 입력

if st.button('대화 미리보기'):
    clean_name = name.strip()
    clean_question = question.strip()
    if not clean_name or not clean_question:
        st.warning('이름과 질문을 모두 입력하세요.')
    else:
        with st.chat_message('user'): # 여러 줄로 입력
            st.text(f"{clean_name}:{clean_question}")
        with st.chat_message('assistant'):
            st.text(f"{clean_name}님 질문을 확인했습니다. 이 화면은 미리보기 입니다.")
else:
    st.caption('이름과 질문을 입력한 뒤 미리보기 버튼을 누르세요.')